FROM python:3.12-slim
WORKDIR /srv
COPY app ./app
ENV PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app.server"]
