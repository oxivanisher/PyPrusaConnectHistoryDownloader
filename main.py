import requests
import csv
import json
import os
import base64
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict


def load_config(config_path="config.json"):
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"Error: Config file '{config_path}' not found!")
        print("Please create a config.json file based on config.json.example")
        exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config, config_path="config.json"):
    """Save configuration to JSON file."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_token_from_user():
    """Prompt user to enter JWT token with helpful instructions."""
    print("\n" + "="*60)
    print("JWT Token Required")
    print("="*60)
    print("\nTo get your JWT token:")
    print("1. Open Prusa Connect in your browser (https://connect.prusa3d.com)")
    print("2. Log in to your account")
    print("3. Open Developer Tools (Press F12)")
    print("4. Go to 'Application' tab (Chrome) or 'Storage' tab (Firefox)")
    print("5. Navigate to: Cookies > https://connect.prusa3d.com")
    print("6. Find the cookie named: auth.access_token")
    print("7. Copy its Value (the long JWT token starting with 'eyJ...')")
    print("\n" + "-"*60)

    while True:
        token = input("\nPaste your JWT token here: ").strip()

        if not token:
            print("Error: Token cannot be empty. Please try again.")
            continue

        # Basic validation - JWT tokens start with "eyJ"
        if not token.startswith("eyJ"):
            print("Warning: This doesn't look like a valid JWT token.")
            print("JWT tokens typically start with 'eyJ'")
            retry = input("Do you want to try again? (y/n): ").strip().lower()
            if retry != 'y':
                break
            continue

        # Check if it has 3 parts (header.payload.signature)
        if token.count('.') != 2:
            print("Warning: JWT tokens typically have 3 parts separated by dots.")
            retry = input("Do you want to try again? (y/n): ").strip().lower()
            if retry != 'y':
                break
            continue

        return token

    return None


def decode_jwt_payload(token):
    """Decode JWT token payload to check expiration."""
    try:
        # JWT structure: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode payload (add padding if needed)
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        print(f"Warning: Could not decode JWT token: {e}")
        return None


def check_token_expiration(token):
    """Check if JWT token is expired."""
    payload = decode_jwt_payload(token)
    if not payload:
        return True, "Could not decode token"

    exp_timestamp = payload.get("exp")
    if not exp_timestamp:
        return True, "No expiration found in token"

    current_time = time.time()
    if current_time >= exp_timestamp:
        exp_date = datetime.fromtimestamp(exp_timestamp)
        return True, f"Token expired on {exp_date}"

    exp_date = datetime.fromtimestamp(exp_timestamp)
    return False, f"Token valid until {exp_date}"


def fetch_page(url, headers):
    """Fetch a single page from the API."""
    try:
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print(f"Error: Authentication failed. Your token may be expired or invalid.")
            print(f"Status code: {e.response.status_code}")
        else:
            print(f"HTTP Error: {e}")
        raise
    except requests.exceptions.RequestException as e:
        print(f"Request Error: {e}")
        raise


def fetch_all_jobs(printer_uuid, jwt_token):
    """Fetch all jobs for a specific printer."""
    base_url = f"https://connect.prusa3d.com/app/printers/{printer_uuid}/jobs"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/json"
    }

    jobs = []
    offset = 0
    page_count = 0
    total_jobs = None

    while True:
        page_count += 1
        url = f"{base_url}?offset={offset}"
        print(f"  Fetching page {page_count} (offset: {offset})...")

        data = fetch_page(url, headers)

        # Get jobs from the response
        page_jobs = data.get("jobs", [])
        jobs.extend(page_jobs)

        # Get pagination info
        pager = data.get("pager", {})
        if total_jobs is None:
            total_jobs = pager.get("total", 0)
            print(f"  Total jobs available: {total_jobs}")

        limit = pager.get("limit", 20)
        current_offset = pager.get("offset", 0)

        print(f"  Retrieved {len(page_jobs)} jobs from page {page_count} (total so far: {len(jobs)}/{total_jobs})")

        # Check if we've fetched all jobs
        if len(jobs) >= total_jobs or len(page_jobs) == 0:
            break

        # Move to next page
        offset += limit

    return jobs


def load_existing_jobs(filepath):
    """Load existing jobs from JSON file if it exists."""
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not load existing data from {filepath}: {e}")
            return []
    return []


def merge_jobs(existing_jobs, new_jobs):
    """
    Merge new jobs with existing jobs, avoiding duplicates based on job ID.

    Optimization: Finished jobs that already exist in the archive are not updated,
    since their data won't change. Only new jobs or in-progress jobs are updated.
    """
    # Create a dictionary of existing jobs by ID for fast lookup
    existing_by_id = {job["id"]: job for job in existing_jobs if "id" in job}

    # States that indicate a job is finished and won't change
    FINISHED_STATES = {"FIN_OK", "FIN_STOPPED", "FIN_FAILED", "FIN_ERROR"}

    stats = {
        "new_jobs": 0,
        "updated_jobs": 0,
        "skipped_finished": 0
    }

    # Update with new jobs (but skip updating finished jobs that already exist)
    for job in new_jobs:
        job_id = job.get("id")
        if not job_id:
            continue

        # Check if this job already exists
        if job_id in existing_by_id:
            existing_job = existing_by_id[job_id]
            existing_state = existing_job.get("state", "")
            new_state = job.get("state", "")

            # If the existing job is finished, keep the archived version
            # (finished jobs don't change, and archive might have more complete data)
            if existing_state in FINISHED_STATES:
                stats["skipped_finished"] += 1
                continue  # Keep existing job, don't update

            # If job is in progress or state changed, update it
            stats["updated_jobs"] += 1

        else:
            # New job not in archive
            stats["new_jobs"] += 1

        # Add or update the job
        existing_by_id[job_id] = job

    # Convert back to list and sort by start time (newest first)
    merged = list(existing_by_id.values())
    merged.sort(key=lambda x: x.get("start", 0), reverse=True)

    return merged, stats


def save_json(jobs, filepath):
    """Save jobs data to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    print(f"  Saved JSON to {filepath}")


def flatten_job_for_csv(job):
    """Flatten job data to extract only useful fields for CSV export."""
    file_obj = job.get("file", {})
    meta = file_obj.get("meta", {})

    # Convert timestamps to readable format
    start_timestamp = job.get("start")
    end_timestamp = job.get("end")

    start_str = None
    if start_timestamp:
        try:
            start_str = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            start_str = None

    end_str = None
    if end_timestamp:
        try:
            end_str = datetime.fromtimestamp(end_timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            end_str = None

    # Convert durations from seconds to hours
    time_printing_seconds = job.get("time_printing")
    time_printing_hours = None
    if time_printing_seconds:
        time_printing_hours = round(time_printing_seconds / 3600, 3)

    estimated_print_time_seconds = meta.get("estimated_print_time")
    estimated_print_time_hours = None
    if estimated_print_time_seconds:
        estimated_print_time_hours = round(estimated_print_time_seconds / 3600, 3)

    flattened = {
        # Job basics
        "id": job.get("id"),
        "state": job.get("state"),
        "start": start_str,
        "end": end_str,
        "time_printing_hours": time_printing_hours,
        "print_height": job.get("print_height"),
        "path": job.get("path"),

        # File info
        "file_name": file_obj.get("display_name") or file_obj.get("name"),
        "file_size": file_obj.get("size"),

        # Filament data from metadata
        "filament_type": meta.get("filament_type"),
        "filament_used_mm": meta.get("filament_used_mm"),
        "filament_used_m": meta.get("filament_used_m"),
        "filament_used_g": meta.get("filament_used_g"),
        "filament_cost": meta.get("filament_cost"),

        # Print settings
        "layer_height": meta.get("layer_height"),
        "nozzle_diameter": meta.get("nozzle_diameter"),
        "temperature": meta.get("temperature"),
        "bed_temperature": meta.get("bed_temperature"),
        "fill_density": meta.get("fill_density"),
        "support_material": meta.get("support_material"),

        # Metadata
        "printer_model": meta.get("printer_model"),
        "estimated_print_time_hours": estimated_print_time_hours,
        "total_height": meta.get("total_height"),
    }

    return flattened


def save_csv(jobs, filepath):
    """Save jobs data to CSV file with flattened structure."""
    if not jobs:
        print("  No jobs to save to CSV")
        return

    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Flatten all jobs
    flattened_jobs = [flatten_job_for_csv(job) for job in jobs]

    # Get all fieldnames from flattened data
    fieldnames = [
        "id", "state", "start", "end", "time_printing_hours", "print_height", "path",
        "file_name", "file_size",
        "filament_type", "filament_used_mm", "filament_used_m", "filament_used_g", "filament_cost",
        "layer_height", "nozzle_diameter", "temperature", "bed_temperature", "fill_density", "support_material",
        "printer_model", "estimated_print_time_hours", "total_height"
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened_jobs)

    print(f"  Saved CSV to {filepath}")


def generate_yearly_stats(jobs, printer_name):
    """Generate yearly statistics from job data."""
    stats_by_year = defaultdict(lambda: {
        "total_jobs": 0,
        "successful": 0,
        "failed": 0,
        "stopped": 0,
        "in_progress": 0,
        "total_print_time_seconds": 0,
        "total_filament_used_mm": 0,
        "total_filament_used_g": 0,
        "materials": {},
    })

    for job in jobs:
        # Extract year from start timestamp (Unix timestamp)
        start_timestamp = job.get("start")
        if not start_timestamp:
            continue

        try:
            # Convert Unix timestamp to datetime
            job_date = datetime.fromtimestamp(start_timestamp)
            year = job_date.year
        except (ValueError, TypeError):
            continue

        year_stats = stats_by_year[year]
        year_stats["total_jobs"] += 1

        # State tracking (FIN_OK, FIN_STOPPED, PRINTING, etc.)
        state = job.get("state", "")
        if state == "FIN_OK":
            year_stats["successful"] += 1
        elif state in ["FIN_FAILED", "FIN_ERROR"]:
            year_stats["failed"] += 1
        elif state == "FIN_STOPPED":
            year_stats["stopped"] += 1
        elif state == "PRINTING":
            year_stats["in_progress"] += 1

        # Print time (in seconds)
        print_time = job.get("time_printing")
        if print_time:
            year_stats["total_print_time_seconds"] += print_time

        # Filament usage from file metadata
        file_obj = job.get("file", {})
        meta = file_obj.get("meta", {})

        filament_mm = meta.get("filament_used_mm")
        if filament_mm:
            year_stats["total_filament_used_mm"] += filament_mm

        filament_g = meta.get("filament_used_g")
        if filament_g:
            year_stats["total_filament_used_g"] += filament_g

        # Track material types
        filament_type = meta.get("filament_type")
        if filament_type:
            if filament_type not in year_stats["materials"]:
                year_stats["materials"][filament_type] = 0
            year_stats["materials"][filament_type] += 1

    return dict(stats_by_year)


def format_duration(seconds):
    """Format seconds into human-readable duration."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{int(hours)}h {int(minutes)}m"


def calculate_total_stats(stats_by_year):
    """Calculate total statistics across all years."""
    totals = {
        "total_jobs": 0,
        "successful": 0,
        "failed": 0,
        "stopped": 0,
        "in_progress": 0,
        "total_print_time_seconds": 0,
        "total_filament_used_mm": 0,
        "total_filament_used_g": 0,
        "materials": {},
    }

    for year_stats in stats_by_year.values():
        for key in ["total_jobs", "successful", "failed", "stopped", "in_progress",
                    "total_print_time_seconds", "total_filament_used_mm", "total_filament_used_g"]:
            totals[key] += year_stats[key]

        # Aggregate materials
        for material, count in year_stats.get("materials", {}).items():
            if material not in totals["materials"]:
                totals["materials"][material] = 0
            totals["materials"][material] += count

    return totals


def print_stats_summary(stats_by_year, printer_name):
    """Print a formatted summary of yearly statistics."""
    print(f"\n{'='*60}")
    print(f"Yearly Statistics for: {printer_name}")
    print(f"{'='*60}")

    for year in sorted(stats_by_year.keys()):
        stats = stats_by_year[year]
        print(f"\n{year}:")
        print(f"  Total Jobs: {stats['total_jobs']}")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Stopped: {stats['stopped']}")
        if stats['in_progress'] > 0:
            print(f"  In Progress: {stats['in_progress']}")
        print(f"  Total Print Time: {format_duration(stats['total_print_time_seconds'])}")
        print(f"  Total Filament Used: {stats['total_filament_used_mm']/1000:.2f} m")
        if stats['total_filament_used_g'] > 0:
            print(f"  Total Filament Weight: {stats['total_filament_used_g']:.2f} g")

        # Show materials breakdown
        if stats.get('materials'):
            materials_str = ", ".join([f"{mat}: {count}" for mat, count in sorted(stats['materials'].items())])
            print(f"  Materials: {materials_str}")

    # Print totals if there are multiple years
    if len(stats_by_year) > 1:
        totals = calculate_total_stats(stats_by_year)
        print(f"\n{'='*60}")
        print("TOTAL (All Years):")
        print(f"  Total Jobs: {totals['total_jobs']}")
        print(f"  Successful: {totals['successful']}")
        print(f"  Failed: {totals['failed']}")
        print(f"  Stopped: {totals['stopped']}")
        if totals['in_progress'] > 0:
            print(f"  In Progress: {totals['in_progress']}")
        print(f"  Total Print Time: {format_duration(totals['total_print_time_seconds'])}")
        print(f"  Total Filament Used: {totals['total_filament_used_mm']/1000:.2f} m")
        if totals['total_filament_used_g'] > 0:
            print(f"  Total Filament Weight: {totals['total_filament_used_g']:.2f} g")

        # Show materials breakdown
        if totals.get('materials'):
            materials_str = ", ".join([f"{mat}: {count}" for mat, count in sorted(totals['materials'].items())])
            print(f"  Materials: {materials_str}")


def main():
    """Main function to orchestrate the job history download."""
    config = load_config()

    # Check if token exists and is not empty
    jwt_token = config.get("jwt_token", "").strip()

    if not jwt_token or jwt_token == "YOUR_JWT_TOKEN_HERE":
        print("No JWT token found in config.json")
        jwt_token = get_token_from_user()

        if not jwt_token:
            print("\nError: Cannot continue without a valid JWT token.")
            return

        # Save token to config
        config["jwt_token"] = jwt_token
        save_config(config)
        print("\n✓ Token saved to config.json")
        print("")

    # Check token expiration
    is_expired, message = check_token_expiration(jwt_token)
    print(f"Token Status: {message}")

    if is_expired:
        print("\nWARNING: Your token appears to be expired or invalid!")
        response = input("\nDo you want to enter a new token? (y/n): ").strip().lower()

        if response == 'y':
            jwt_token = get_token_from_user()

            if not jwt_token:
                print("\nError: Cannot continue without a valid JWT token.")
                return

            # Save new token to config
            config["jwt_token"] = jwt_token
            save_config(config)
            print("\n✓ Token updated in config.json")

            # Re-check new token
            is_expired, message = check_token_expiration(jwt_token)
            print(f"Token Status: {message}")

            if is_expired:
                print("\nWARNING: The new token also appears to be expired or invalid!")
                print("Please check that you copied the correct token value.")
                return
        else:
            return

    print("")

    # Get output settings
    output_config = config.get("output", {})
    output_dir = Path(output_config.get("directory", "output"))
    save_json_enabled = output_config.get("save_json", True)
    save_csv_enabled = output_config.get("save_csv", True)

    # Process each printer
    printers = config.get("printers", [])
    if not printers:
        print("Error: No printers configured in config.json")
        return

    all_stats = {}

    for printer in printers:
        printer_name = printer["name"]
        printer_uuid = printer["uuid"]

        print(f"\nProcessing printer: {printer_name} ({printer_uuid})")
        print("-" * 60)

        try:
            safe_name = printer_name.replace(" ", "_").lower()
            json_path = output_dir / f"{safe_name}_jobs.json"

            # Load existing jobs (if any)
            existing_jobs = load_existing_jobs(json_path)
            if existing_jobs:
                print(f"  Found {len(existing_jobs)} existing jobs in archive")

            # Fetch new jobs from API
            new_jobs = fetch_all_jobs(printer_uuid, jwt_token)
            print(f"  Downloaded {len(new_jobs)} jobs from API (last 3 months)")

            # Merge existing and new jobs
            all_jobs, merge_stats = merge_jobs(existing_jobs, new_jobs)

            # Display merge statistics
            if merge_stats["new_jobs"] > 0:
                print(f"  Added {merge_stats['new_jobs']} new jobs to archive")
            if merge_stats["updated_jobs"] > 0:
                print(f"  Updated {merge_stats['updated_jobs']} in-progress jobs")
            if merge_stats["skipped_finished"] > 0:
                print(f"  Skipped {merge_stats['skipped_finished']} finished jobs (already in archive)")
            if merge_stats["new_jobs"] == 0 and merge_stats["updated_jobs"] == 0:
                print(f"  No new jobs (all jobs already in archive)")

            print(f"  Total jobs in archive: {len(all_jobs)}")

            if not all_jobs:
                print(f"  No jobs found for {printer_name}")
                continue

            # Save merged data
            if save_json_enabled:
                save_json(all_jobs, json_path)

            if save_csv_enabled:
                csv_path = output_dir / f"{safe_name}_jobs.csv"
                save_csv(all_jobs, csv_path)

            # Save metadata about last update
            metadata = {
                "last_updated": datetime.now().isoformat(),
                "total_jobs": len(all_jobs),
                "jobs_in_api": len(new_jobs),
                "printer_name": printer_name,
                "printer_uuid": printer_uuid
            }
            metadata_path = output_dir / f"{safe_name}_metadata.json"
            save_json(metadata, metadata_path)

            # Generate and store stats (based on ALL jobs, not just new ones)
            yearly_stats = generate_yearly_stats(all_jobs, printer_name)
            all_stats[printer_name] = yearly_stats

            # Save yearly stats
            stats_path = output_dir / f"{safe_name}_yearly_stats.json"
            save_json(yearly_stats, stats_path)

            # Calculate and save total stats
            if len(yearly_stats) > 0:
                total_stats = calculate_total_stats(yearly_stats)
                total_stats_path = output_dir / f"{safe_name}_total_stats.json"
                save_json(total_stats, total_stats_path)

            # Print summary
            print_stats_summary(yearly_stats, printer_name)

        except Exception as e:
            print(f"  Error processing {printer_name}: {e}")
            continue

    print(f"\n{'='*60}")
    print("Download completed!")
    print(f"Output saved to: {output_dir.absolute()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
