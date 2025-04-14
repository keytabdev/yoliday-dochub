# yoliday-dochub

# Deployment Instructions for Yoliday-DocHub

## Prerequisites

Before running the application, make sure you have the following installed:

- Python 3.7+ 
- pip (Python package installer)

## Installation Steps

1. **Create a new directory for your project**

```bash
mkdir yoliday-dochub
cd yoliday-dochub
```

2. **Create a virtual environment (recommended)**

```bash
python -m venv venv
```

3. **Activate the virtual environment**

On Windows:
```bash
venv\Scripts\activate
```

On macOS/Linux:
```bash
source venv/bin/activate
```

4. **Create a requirements.txt file**

Create a file named `requirements.txt` with the following content:

```
streamlit>=1.21.0
requests>=2.28.0
pandas>=1.3.0
```

5. **Install the dependencies**

```bash
pip install -r requirements.txt
```

6. **Save the Streamlit app code**

Save the provided Streamlit app code in a file named `app.py` in your project directory.

7. **Run the Streamlit app**

```bash
streamlit run app.py
```

The app should now be running at http://localhost:8501 (or another port if 8501 is already in use).

## Usage Notes

### Meilisearch Backup

1. Enter your Meilisearch URL and API key in the sidebar
2. Click "Get All Indexes" to see available indexes
3. Select the indexes you want to backup
4. Click "Backup Selected Indexes"
5. Download the backup file when processing is complete

### Meilisearch Restore

1. Upload a previously created backup file
2. Select which indexes you want to restore
3. Click "Restore Selected Indexes"
4. Monitor the progress in the application

### Embed Documents

1. Enter the embedding API URL in the sidebar
2. Choose whether to embed a text document or a PDF from an S3 URL
3. Fill in the required fields
4. Click the "Embed Text" or "Embed PDF" button

### Ask Questions

1. Click "Refresh Available Indexes" to get a list of available indexes
2. Select an index to query
3. Enter your question
4. Adjust the number of results (k) if needed
5. Click "Ask Question"
6. View the answer and relevant sources

## Troubleshooting

- If you encounter connection errors with Meilisearch, verify that your URL and API key are correct
- If the embedding API returns errors, check the API URL and ensure your request payload is formatted correctly
- For permission issues with file downloads, ensure your browser allows downloads from the application

## Production Deployment

For production deployment, consider:

1. Using a proper authentication mechanism
2. Configuring environment variables for API keys and URLs
3. Deploying behind a secure proxy like Nginx
4. Using Streamlit Sharing, Heroku, or similar platforms for hosting

You can deploy this app on Streamlit Cloud by:
1. Pushing this code to a GitHub repository
2. Connecting the repository to Streamlit Cloud
3. Setting the necessary secrets in the Streamlit Cloud dashboard
