# deadreckon

**Build with DataHub: The Agent Hackathon — Challenge #3, Production ML Agents**

Models in production rarely fail loudly. More often they rot quietly, because
something changed four hops upstream in the data chain and nobody connected
the dots between the table, the feature, the training run, and the deployed
endpoint.

deadreckon is an agent that walks full ML lineage in DataHub, detects three
classes of silent failure using metadata alone, scores them by weight and
blast radius, and writes the risk assessment back into the graph next to the
model it concerns.

**Design constraint, not a shortcut:** deadreckon operates on metadata only.
No access to model runtime, no serving, no drift computed on live
predictions. ML teams typically have model monitoring and data monitoring as
two separate systems — the silence between them is where money goes missing.

## Status

Early scaffold. See `NOTES.md` for build-in-progress notes and
documentation issues found along the way.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
