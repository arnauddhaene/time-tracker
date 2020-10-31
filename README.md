[![GitHub flake8 Linter](https://github.com/arnauddhaene/time-tracker/workflows/flake8%20lint/badge.svg)](https://github.com/marketplace/actions/python-flake8-lint)


## Purpose

Create an interactive dashboard to analyze time spent. Is still personalized to fetch from two specific calendars for now. Might be generalized later on.

## Development
### Create conda environment

`conda create --name time-tracker python=3.6 --file requirements.txt`

### Fetch credentials from Google Developers Console

Save as `personal-credentials.json` file in root directory.

### Environment config

For config variables such as calendar IDs, create a `.env` file.

### Run development server

`python app.py`

## Author

Arnaud Dhaene
