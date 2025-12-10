# syntax=docker/dockerfile:1

FROM python:3.13.7-trixie

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

WORKDIR /fall25-uva-ds6600-climatefuture-jf

EXPOSE 8888

CMD ["jupyter", "lab","--ip=0.0.0.0","--allow-root"]

