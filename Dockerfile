# Use an official lightweight Python image that includes build tools
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies, including wget and unzip, then install Google Chrome
# This is a more modern and reliable method
RUN apt-get update && apt-get install -y wget unzip gnupg \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-archive-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-archive-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install ChromeDriver automatically using a helper script
RUN apt-get install -y chromium-driver

# Copy and install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port the app will run on
EXPOSE 10000

# Command to run the application
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "app:app"]
