FROM ubuntu:latest
LABEL authors="ayush"

ENTRYPOINT ["top", "-b"]