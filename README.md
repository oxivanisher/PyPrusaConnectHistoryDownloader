# Prusa Connect History Downloader

Download and analyze print job history from Prusa Connect for your 3D printers.

## Attention - Vibe Coded

Please be aware, that this application is (almost) completely vibe-coded. It works in my use case and the code seemed sensible to me but ... you have been warned.

## Features

- Download complete job history for multiple printers
- Support for multiple printers with custom names
- Automatic JWT token validation and expiration checking
- Export data to JSON and CSV formats
- Generate yearly statistics including:
  - Total jobs, successful/failed/cancelled counts
  - Total print time
  - Total filament usage (length and weight)
- Error handling and detailed logging

## Setup

### 1. Install Dependencies

```bash
pip install requests
```

### 2. Get Your JWT Token

The script uses the `auth.access_token` cookie from your browser.

**Option A: Interactive Entry (Recommended for first-time users)**

Simply run the script without a token in config.json, and it will guide you through the process:

```bash
python main.py
```

The script will interactively prompt you with step-by-step instructions and automatically save the token to your config.

**Option B: Manual Configuration**

1. Open [Prusa Connect](https://connect.prusa3d.com) in your browser
2. Log in to your account
3. Open Developer Tools (F12)
4. Go to **Application** (Chrome) or **Storage** (Firefox) tab
5. Navigate to **Cookies** > `https://connect.prusa3d.com`
6. Find the cookie named `auth.access_token`
7. Copy its value (it's a long JWT token starting with `eyJ...`)
8. Add it to `config.json`

**Note:** This token is correct and will work with the API. It expires periodically. When it expires, the script will ask if you want to enter a new one.

### 3. Configure Your Printers

Edit `config.json` and add your printer information:

```json
{
  "jwt_token": "YOUR_JWT_TOKEN_HERE",
  "printers": [
    {
      "name": "My Printer",
      "uuid": "your-printer-uuid-here"
    },
    {
      "name": "MK4",
      "uuid": "another-printer-uuid-here"
    }
  ],
  "output": {
    "directory": "output",
    "save_json": true,
    "save_csv": true
  }
}
```

#### Finding Your Printer UUID

1. Go to Prusa Connect and select your printer
2. Look at the URL in your browser
3. The UUID is the long string after `/printers/`
   - Example: `https://connect.prusa3d.com/app/printers/your-printer-uuid-here`
   - UUID: `your-printer-uuid-here`

## Usage

Run the script:

```bash
python main.py
```

The script will:
1. Validate your JWT token and check expiration
2. Load existing job history (if any)
3. Download job history from Prusa Connect (last 3 months)
4. Merge new data with existing archive (avoiding duplicates)
5. Save updated data to JSON and CSV files
6. Generate yearly statistics for all historical data
7. Display a summary in the console

## Incremental Updates (Preserving History)

**IMPORTANT**: Prusa Connect only keeps job history for the last 3 months. To preserve your complete printing history, run this script monthly.

### How It Works

The script automatically:
- **Loads existing data** from previous runs
- **Merges new jobs** with historical data (using job ID as unique identifier)
- **Preserves old jobs** that are no longer in the API
- **Updates existing jobs** with latest information
- **Tracks metadata** including last update time

### Running Monthly

1. **First Run**: Downloads all jobs from the last 3 months
2. **Subsequent Runs**:
   - Detects existing archive
   - Downloads current jobs from API
   - Adds only new jobs to archive
   - Keeps old jobs that dropped off the 3-month window

### Example Output

```
Processing printer: My Printer (your-printer-uuid-here)
------------------------------------------------------------
  Found 106 existing jobs in archive
  Downloaded 106 jobs from API (last 3 months)
  No new jobs (all jobs already in archive)
  Total jobs in archive: 106
```

Next month, when you have new prints:
```
  Found 106 existing jobs in archive
  Downloaded 120 jobs from API (last 3 months)
  Added 14 new jobs to archive
  Total jobs in archive: 120
```

### Metadata File

Each printer gets a metadata file (`<printer_name>_metadata.json`) that tracks:
- Last update timestamp
- Total jobs in archive
- Number of jobs currently in API
- Printer name and UUID

This helps you monitor your data collection over time.

## Output Files

For each printer, the following files are created in the `output/` directory:

- `<printer_name>_jobs.json` - Complete job data in JSON format (all historical data)
- `<printer_name>_jobs.csv` - Complete job data in CSV format (human-readable with timestamps)
- `<printer_name>_yearly_stats.json` - Yearly statistics summary with material breakdown
- `<printer_name>_total_stats.json` - Total statistics across all years
- `<printer_name>_metadata.json` - Metadata about last update and archive status

### Example Output

```
Token Status: Token valid until 2055-10-21 12:04:23.644046

Processing printer: My Printer (your-printer-uuid-here)
------------------------------------------------------------
  Found 150 existing jobs in archive
  Fetching page 1 (offset: 0)...
  Total jobs available: 106
  Retrieved 20 jobs from page 1 (total so far: 20/106)
  ...
  Downloaded 106 jobs from API (last 3 months)
  Added 6 new jobs to archive
  Total jobs in archive: 156
  Saved JSON to output\my_printer_jobs.json
  Saved CSV to output\my_printer_jobs.csv
  Saved JSON to output\my_printer_metadata.json
  Saved JSON to output\my_printer_yearly_stats.json
  Saved JSON to output\my_printer_total_stats.json

============================================================
Yearly Statistics for: My Printer
============================================================

2024:
  Total Jobs: 50
  Successful: 46
  Failed: 2
  Stopped: 2
  Total Print Time: 287h 34m
  Total Filament Used: 1234.56 m
  Total Filament Weight: 3456.78 g
  Materials: PLA: 35, PETG: 12, PC: 3

2025:
  Total Jobs: 106
  Successful: 82
  Failed: 0
  Stopped: 23
  In Progress: 1
  Total Print Time: 163h 8m
  Total Filament Used: 1765.00 m
  Total Filament Weight: 5286.04 g
  Materials: PLA: 58, PETG: 37, PC: 11

============================================================
TOTAL (All Years):
  Total Jobs: 156
  Successful: 128
  Failed: 2
  Stopped: 25
  In Progress: 1
  Total Print Time: 450h 42m
  Total Filament Used: 2999.56 m
  Total Filament Weight: 8742.82 g
  Materials: PLA: 93, PETG: 49, PC: 14

============================================================
Download completed!
Output saved to: C:\...\output
============================================================
```

## Troubleshooting

### Token Expired Error

If you see "Token expired" or authentication errors:

1. Get a fresh token from your browser (see Setup step 2)
2. Update `config.json` with the new token
3. Run the script again

### 401 Authentication Failed

This usually means:
- Your token has expired
- The token was copied incorrectly (make sure to copy the entire token)

### No Jobs Found

- Verify the printer UUID is correct
- Make sure the printer has print history in Prusa Connect

## Data Fields

The job data includes fields such as:
- `started_at` - When the job started
- `finished_at` - When the job finished
- `status` - Job status (done, failed, cancelled, etc.)
- `time_printing` - Actual print time in seconds
- `filament_used` - Filament used in millimeters
- `filament_weight` - Filament weight in grams
- And many more fields depending on your printer model

See the CSV output for all available fields.

## Adding Multiple Printers

Simply add more entries to the `printers` array in `config.json`:

```json
{
  "jwt_token": "...",
  "printers": [
    {
      "name": "My Printer",
      "uuid": "your-printer-uuid-here"
    },
    {
      "name": "MK4 Living Room",
      "uuid": "uuid-for-mk4-printer"
    },
    {
      "name": "Mini+ Workshop",
      "uuid": "uuid-for-mini-printer"
    }
  ],
  "output": {
    "directory": "output",
    "save_json": true,
    "save_csv": true
  }
}
```

Each printer will be processed sequentially and get its own set of output files.

## License

MIT — see [LICENSE](LICENSE).
