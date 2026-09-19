# The CloudWatch feeder. It runs the bot's own `healthbot-local feed`, not a
# reimplementation of it, so the datapoints are always shaped the way
# checks/aws.py expects. That is the whole reason this container installs
# the package instead of calling put_metric_data itself.
FROM python:3.12-slim

WORKDIR /src
# Only what the wheel build reads. The build context is the repository root
# (see .dockerignore), and hatchling needs the readme pyproject names.
COPY pyproject.toml README.md ./
COPY healthbot ./healthbot
RUN pip install --no-cache-dir .

COPY IT/local/feeder/healthcheck.py /usr/local/bin/healthcheck.py

# It writes nothing and opens no port, so it has no reason to be root.
RUN useradd --system --no-create-home feeder
USER feeder

# Healthy means CloudWatch holds a recent datapoint, not that the process is
# alive: a feeder that has lost the AWS emulator is the failure that matters.
HEALTHCHECK --interval=60s --timeout=10s --start-period=90s \
    CMD ["python", "/usr/local/bin/healthcheck.py"]

# Once a minute. checks/aws.py reads the newest datapoint in a five-minute
# window, so a longer gap makes the AWS check read as "could not collect".
CMD ["healthbot-local", "feed", "--interval", "60"]
