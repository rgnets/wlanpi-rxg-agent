FROM debian:12
LABEL authors="Michael Ketchel <michael.ketchel@gmail.com>"

RUN apt update && apt satisfy --yes " \
    debhelper (>= 11), \
    bash, \
    python3-distutils, \
    dh-python, \
    dh-virtualenv (>= 1.2), \
    debhelper-compat (= 13), \
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

ENV EDITOR=vim
WORKDIR /mnt

CMD ["bash"]