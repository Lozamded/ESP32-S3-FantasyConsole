---
id: object-identity
sidebar_position: 3
title: Object Identity & Visibility
---

# Object Identity & Visibility (v0)

Objects placed in a scene can have an **instance identity** (id, tags) for runtime lookup, and a **visibility flag** that controls whether the object draws.

---

## Instance identity

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `object` | string | — | Catalog reference — the stem in `objects/<stem>.json`. Tells the firmware which sprite, script, and collision shape to use. |
| `id` | string | `""` | **Instance** identifier. Unique within the scene. Used by `find_by_id`. Max 32 chars. |
| `tags` | string[] | `[]` | Arbitrary labels for group lookup via `find_by_tag`. Up to **6 tags** per instance, each max 20 chars. |

`object` and `id` are separate concerns: the same `object` catalog entry (e.g. `"coin"`) can be placed many times in a scene, each with a distinct `id` and different `tags`.

```json
{
  "object": "coin",
  "id": "coin_01",
  "tags": ["collectible", "level1"],
  "x": 80, "y": 40
}
```

**Legacy compatibility:** if a scene object dict has no `"object"` key, the firmware uses `"id"` as the catalog reference (pre-v0 behavior where id doubled as the type). New projects should always include `"object"`.

---

## Runtime Lua API

All handle-based functions are available from both ENTRY and actor VMs.

| Function | Description |
|----------|-------------|
| `find_by_id(id)` → handle \| nil | Find the actor instance with the given `id`. Returns `nil` if not found or already destroyed. |
| `find_by_tag(tag)` → table | Find all visible actor instances that have `tag` in their `tags` array. Returns an empty table if none. |
| `obj_posx(handle)` → number | X position of the actor in scene coordinates. |
| `obj_posy(handle)` → number | Y position of the actor in scene coordinates. |
| `obj_id(handle)` → string | The instance `id` string of the handle. |
| `obj_has_tag(handle, tag)` → bool | Test whether the handle has a specific tag. |

Handles are **opaque** — do not store them across scene changes. A handle is invalidated when the scene ends or the actor is destroyed; using a stale handle is a silent no-op (returns `nil`/`false`).

```lua
-- Example: deactivate all "coin" actors on collection
local coins = find_by_tag("collectible")
for _, h in ipairs(coins) do
  if obj_posx(h) > 60 and obj_posx(h) < 90 then
    -- actor is near the player; do something
  end
end
```

:::note
In v0 all handle data is **read-only** — you can query position, id, and tags, but cannot move, destroy, or modify actors via handles. Use actor scripts for self-modification.
:::

---

## Visibility

### Scene manifest field

```json
{
  "object": "gem",
  "id": "gem_secret",
  "visible": false,
  "x": 100, "y": 20
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `visible` | bool | `true` | Whether the object's sprite is drawn. Affects drawing only — see below. |

### What visibility controls (and doesn't)

**Affected by `visible: false`:**
- The actor's sprite is not drawn on any frame.

**Not affected by `visible: false`:**
- The actor still ticks (`_update(dt)` runs normally).
- The actor still moves and resolves tile collision.
- The actor is still findable via `find_by_id` and `find_by_tag`.
- The actor still participates in scene state.

`visible` is a static property set in the scene manifest. In v0 there is no `set_visible()` Lua call — an actor that starts invisible stays invisible. Use a `visible: false` actor as a silent trigger zone or invisible platform, or as a placeholder for a feature you plan to reveal in a future firmware version.

:::tip
For a "hidden then revealed" game mechanic in v0, use two objects: a `visible: false` trigger actor and a `visible: true` gem actor. The trigger's `_update` can call `goto_scene` or set a `state` flag to control game flow.
:::

---

## TurtleStudio

- The scene editor shows instance id and tags as editable fields in the object inspector.
- Objects with `visible: false` are shown at 50% opacity in the canvas preview and marked with a hidden-eye icon.
- `find_by_id` / `find_by_tag` results are reflected in the Play simulator.

---

## Out of scope in v0

- `set_visible(handle, bool)` — runtime visibility toggle from Lua (planned for v1)
- Actor destruction from outside the actor's own script
- Inter-actor messaging
