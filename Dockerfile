FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Core modules
COPY ai_parser.py bot.py config.py data.py excel_ops.py \
     file_storage.py formatters.py models.py scheduled.py \
     scheduled_report.py states.py ./

# Handler package
COPY handlers/ ./handlers/

CMD ["python", "bot.py"]
