# Use official Python image
FROM python:3-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source code
COPY . .

# Bake the image tag into version.py at build time.
# ARG is placed after COPY so the pip install layer stays cached across version bumps.
ARG APP_VERSION=dev
RUN echo "VERSION = '${APP_VERSION}'" > /app/version.py

# Set environment variables (optional)
# ENV DISCORD_TOKEN=your_token_here

# Expose port 8080
EXPOSE 8080
# Command to run the bot
CMD ["python", "main.py"]
