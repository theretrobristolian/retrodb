# RetroNAS integration

This directory is reserved for the future RetroNAS installer or Ansible role.

RetroDB will be developed and tested as a standalone service first. Once its deployment contract is stable, this integration should:

- install the same release used by standalone deployments
- map RetroNAS storage paths explicitly
- create an unprivileged service account
- keep PostgreSQL private
- avoid changing or exposing unrelated RetroNAS services
- support repeatable install, repair, update and removal
- follow RetroNAS project conventions

Nothing in this directory is currently installable.
