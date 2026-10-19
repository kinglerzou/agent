FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home studio
COPY apps/api/studio ./studio
COPY skills /skills
RUN mkdir /data && chown studio:studio /data
ENV STUDIO_DB=/data/studio.sqlite3 PYTHONDONTWRITEBYTECODE=1 STUDIO_SKILLS=/skills
USER studio
EXPOSE 3001
CMD ["uvicorn", "studio.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "3001"]
