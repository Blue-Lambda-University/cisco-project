FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

RUN apt-get update
RUN apt-get install -y vim

WORKDIR /app

# Install Python libraries
RUN python3 -m pip install --upgrade pip
COPY requirements.txt /app/
RUN pip3 install -r /app/requirements.txt

COPY app /app/app

# Setup main script for service
COPY start.sh /app/
RUN chmod +x /app/start.sh
ENV PORT=8006

RUN mkdir logs

# -- Run main script (container code) --
CMD ["./start.sh"]
# CMD ["sleep", "1200"]
