ARG GEONODE_BASE_IMAGE=geonode/geonode:latest
FROM ${GEONODE_BASE_IMAGE}
MAINTAINER GeoNode development team

COPY requirements.txt /usr/src/app/
RUN pip install -r requirements.txt --no-deps

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
