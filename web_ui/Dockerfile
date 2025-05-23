FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the web_ui and all project content under /app
COPY ../../eportem /app

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Ensure output is not buffered
ENV PYTHONUNBUFFERED=1

# Set default env for mock; can be overridden by docker-compose
ENV USE_MOCK_SERVER=NO

# Expose default Flask port (can be remapped outside)
EXPOSE 8010

# Command to run the web UI server
CMD ["python", "web_ui/server.py"]