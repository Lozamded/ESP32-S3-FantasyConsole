-- Punto de control: detecta contacto del jugador, activa animacion "on" y
-- guarda posicion de respawn en estado global (persiste al reiniciar escena).

-- AABB del sprite check_PC (32x32, origin_x=16, origin_y=0)
local self_x0, self_x1, self_y0, self_y1 = -16, 16, 0, 32
-- AABB del jugador (de player.json)
local player_x0, player_x1, player_y0, player_y1 = -9, 8, 0, 27

local activated = false
local first_frame = true

function _update(dt)
  if first_frame then
    first_frame = false
    -- Restaurar animacion "on" si este checkpoint fue el ultimo activado al reiniciar escena.
    -- La posicion del checkpoint es su identificador unico en la escena.
    if state_get("checkpoint_active", 0) == 1 and
       state_get("checkpoint_x", 0) == posx() and
       state_get("checkpoint_y", 0) == posy() then
      activated = true
      set_anim("on")
    end
    return
  end

  if activated then return end

  local player_h = find_by_id("player")
  if not player_h then return end

  local px = obj_posx(player_h)
  local py = obj_posy(player_h)
  local cx = posx()
  local cy = posy()

  if (px + player_x1) > (cx + self_x0) and
     (px + player_x0) < (cx + self_x1) and
     (py + player_y1) > (cy + self_y0) and
     (py + player_y0) < (cy + self_y1) then
    activated = true
    set_anim("on")
    state_set("checkpoint_active", 1)
    state_set("checkpoint_x", cx)
    state_set("checkpoint_y", cy)
  end
end
