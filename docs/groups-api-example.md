# Create a Group, Run All checks and Stream the results

## Create the group

```
~ curl 'http://localhost:5173/api/groups' \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-raw '{"name":"Event 0002","workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"]}'
{"id":2,"group_id":"e0155ab0-c879-4971-8994-bb4182ae6ed7","name":"Event 0002","babylon_cluster":"","source_guids":[],"source_workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"],"source_resource_pools":[],"source_metadata":{},"status":"completed","pinned":false,"created_at":"2026-11-13T04:50:03.837564Z","metadata_syncing":false}
```

## Groups are idempotent (the request body is hashed)

```
~ curl 'http://localhost:5173/api/groups' \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-raw '{"name":"Event 0002","workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"]}'
{"id":2,"group_id":"e0155ab0-c879-4971-8994-bb4182ae6ed7","name":"Event 0002","babylon_cluster":"","source_guids":[],"source_workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"],"source_resource_pools":[],"source_metadata":{},"status":"completed","pinned":false,"created_at":"2026-11-13T04:50:03.837564Z","metadata_syncing":false}
```

## Run All checks for the group

```
~ curl 'http://localhost:5173/api/groups/e0155ab0-c879-4971-8994-bb4182ae6ed7/run' \
  -X POST
{"status":"started"}
```

## Stream the results

```
~ curl -N -H "Accept: text/event-stream" http://localhost:5173/api/groups/e0155ab0-c879-4971-8994-bb4182ae6ed7/stream
event: group_update
data: {"group":{"id":2,"group_id":"e0155ab0-c879-4971-8994-bb4182ae6ed7","name":"Event 0002","babylon_cluster":"","source_guids":[],"source_workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"],...}

event: group_update
data: {"group":{"id":2,"group_id":"e0155ab0-c879-4971-8994-bb4182ae6ed7","name":"Event 0002","babylon_cluster":"","source_guids":[],"source_workshop_guids":["wk2mpt","9z3nj3","cvvtt3","bhbd3j"],...}
```
