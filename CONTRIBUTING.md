# Contributing

Contributions are welcome under 0BSD.

1. Create a focused branch.
2. Do not include credentials, private infrastructure details, or generated
   files.
3. Update the JSON Schema, semantic validator, examples, and tests together
   when the configuration contract changes.
4. Update compatibility locks only from official upstream sources.
5. Run `make check`.
6. Describe deployment impact and validation in the pull request.

Do not upgrade Graylog, Data Node, MongoDB, or OpenSearch independently. Add a
compatibility test and migration note with every pin change.
