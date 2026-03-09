# Use official Python image
FROM python:3-alpine

# Set working directory
RUN apk add --no-cache ffmpeg
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source code
COPY . .

# Set environment variables (optional)
# ENV DISCORD_TOKEN=your_token_here

# Expose port 8080
EXPOSE 8080
# Command to run the bot
CMD ["python", "main.py"]
