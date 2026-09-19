# Security policy

## Supported versions

The `main` branch is supported, and tagged releases get fixes for the current
minor version.

## The machine image is not scanned

**Nothing here scans the AMI, and no software bill of materials is produced.**
`IT/packer` starts from an official Ubuntu image, installs packages over SSH and
publishes the result. No build step runs a vulnerability scanner over it, and no
step emits an inventory of what ended up on the disk.

`IT/terraform` then picks that image up by its `Service` tag, so the instance it
creates boots an image nobody has scanned.

What that costs you: the image is only as current as the base image and the
packages on the day it was built, and there is no list of what is on it to check
a future advisory against. If either matters where you work, scan the AMI with
your own tool before you boot it, and rebuild when the base image is patched.
This repository will not do it for you or tell you when it is due.

## Reporting a vulnerability

**Don't open a public issue.**

Report privately through GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, which opens a draft advisory only the maintainers can see.
Or email **code@kingletas.com**.

Tell us what it does wrong, how to reach it, and what an attacker gets. A
failing test is the clearest report there is.

You'll get an acknowledgement, a triage verdict, and for anything confirmed, a
fix with a regression test and a sweep for the rest of that defect's class.
