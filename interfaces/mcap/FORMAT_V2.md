# Forge MCAP Format v2

This document defines the language-independent compatibility contract shared by Forge MCAP recorders, playback nodes, and dataset converters.

## Identification

A Forge v2 file SHOULD contain an MCAP Metadata record named `forge.mcap` with:

| Key | Requirement | Value |
| --- | --- | --- |
| `format` | required for metadata-based detection | `forge_runtime.mcap` |
| `format_version` | required for metadata-based detection | `2` |
| `metadata_schema_version` | recommended | `2` |

The historical `forge_runtime.mcap` value is a stable wire-format identifier. Extracting the recorder from the runtime does not rename it.

Readers MUST support payload-shape fallback for legacy files that do not contain `forge.mcap`. Writers MAY include additional string-valued fields in this record.

## Canonical topics

- `proprio_state`: robot state, normally a `forge_msgs.JointState` Arrow RecordBatch converted with `to_pydict()` and serialized as JSON.
- `action`: robot command, normally a `forge_msgs.JointCommand` Arrow RecordBatch converted with `to_pydict()` and serialized as JSON.
- Image topics retain their Dora input IDs. Names containing `image` or `camera` are conventionally treated as image topics.

The `proprio_state` and `action` names are retained for compatibility with existing datasets and playback nodes.

## Channel and payload encoding

All Forge v2 channels currently use MCAP `message_encoding=json`. Payloads MUST be standards-compliant JSON; non-finite numeric literals such as `NaN` and `Infinity` are forbidden.

### Joint and generic topics

Arrow values are converted to a Python/Rust JSON object representing named columns. A typical joint payload is:

```json
{
  "name": [["joint_a", "joint_b"]],
  "position": [[1.0, 2.0]],
  "velocity": [[]],
  "effort": [[]]
}
```

Readers MUST tolerate optional JointState/JointCommand columns and SHOULD use `name` to align values.

### Images

Image channels reference a JSON Schema named `foxglove.CompressedImage`, encoded as `jsonschema`. Messages have:

```json
{
  "timestamp": {"sec": 0, "nsec": 0},
  "frame_id": "",
  "data": "<base64>",
  "format": "jpeg"
}
```

Supported `format` values are `jpeg`, `png`, `webp`, and `avif`. Forge raw `rgb8`, `bgr8`, and `mono8` images are normally converted to JPEG; `16UC1` depth images are converted to 16-bit PNG.

## Structured metadata

All MCAP metadata values are strings. Structured values are encoded as compact, standards-compliant JSON strings; non-finite numbers are rejected rather than serialized.

- `forge.robot`: static robot identity/configuration supplied at session start.
- `forge.features`: static dataset feature description supplied at session start.
- `forge.workflow`: session metadata finalized before `Writer.finish()`.

`forge.workflow` may include caller-supplied workflow fields and SHOULD include:

- `status`
- `frame_count`
- `duration_ns`
- `ended_at_unix_ns`
- `ended_at`
- `topics`
- `image_topics`
- `errors` when finalization follows a recording failure

Unknown metadata records and unknown keys MUST be ignored by readers.

## Time and frame semantics

All messages in one recorder snapshot use the same `log_time` and `publish_time` in Unix nanoseconds. A recorder may use sample-and-hold: once a topic has produced a valid value, later snapshots may repeat it until a newer value arrives.

A frame is a logical group of messages sharing a snapshot timestamp. MCAP itself does not provide an atomic frame record; readers group channels by timestamp or use the canonical proprio/action timeline.
