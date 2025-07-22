# Use an official lightweight Python image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies, including wget and unzip, then install Google Chrome
RUN apt-get update && apt-get install -y wget unzip gnupg \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-archive-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-archive-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver
RUN CHROME_MAJOR_VERSION=$(google-chrome --version | sed -E 's/.* ([0-9]+)\..*/\1/') \
    && CHROME_DRIVER_VERSION=$(wget -q -O - "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build.json" | grep -oE "\"${CHROME_MAJOR_VERSION}\.[^\"]+\": {\"version\": \"([^\"]+)\"" | head -1 | sed -E 's/.*"version": "([^"]+)".*/\1/') \
    && wget -q --continue -P /tmp/ https://storage.googleapis.com/chrome-for-testing-public/${CHROME_DRIVER_VERSION}/linux64/chromedriver-linux64.zip \
    && unzip /tmp/chromedriver-linux64.zip -d /usr/local/bin/ \
    && rm /tmp/chromedriver-linux64.zip

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port the app will run on
EXPOSE 10000

# Command to run the application
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]
