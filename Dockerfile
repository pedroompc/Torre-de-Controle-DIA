FROM python:3.12-slim

WORKDIR /app

# Instala dependências do sistema (necessário para oracledb)
RUN apt-get update && apt-get install -y \
    libaio1 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o projeto
COPY . .

# Cria pasta de logs
RUN mkdir -p app/logs

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
