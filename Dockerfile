FROM mageai/mageai:latest

# Set work directory
WORKDIR /home/src

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories
RUN mkdir -p /home/src/mage_data
RUN mkdir -p /home/src/pipelines

# Set environment variables
ENV MAGE_DATA_DIR=/home/src/mage_data
ENV PYTHONPATH="${PYTHONPATH}:/home/src"

# Expose port
EXPOSE 6789

# Start Mage
CMD ["mage", "start", "mage_project"]
