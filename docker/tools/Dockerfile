FROM python:3.12-bullseye
LABEL authors="Michael Ketchel <michael.ketchel@gmail.com>"

RUN apt update && apt satisfy --yes " \
    debhelper (>= 11), \
    bash, \
    python3-distutils, \
    dh-python, \
    dh-virtualenv (>= 1.2), \
    debhelper-compat (= 13), \
    dbus, \
    libcairo2-dev, \
    libdbus-1-3, \
    libdbus-1-dev, \
    libdbus-glib-1-dev, \
    libffi-dev, \
    libgirepository1.0-dev, \
    libglib2.0-0, \
    libglib2.0-dev, \
    python3 (>=3.9), \
    python3-dev, \
    python3-setuptools, \
    python3-distutils, \
    python3-venv, \
    python3-toml, \
    python3-systemd, \
    libsystemd0, \
    devscripts, \
    vim \
    "
#
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
#
#COPY . .
#
#CMD [ "python", "./your-daemon-or-script.py" ]

#COPY ./requirements /requirements.txt
#RUN pip install -U pip pip-tools && pip install --no-cache-dir  -r /requirements.txt && rm -rf /requirements.txt
#RUN pip install -U pip pip-tools mypy black flake8 autoflake pytest

ENV EDITOR=vim
#WORKDIR /mnt

#CMD ["bash"]