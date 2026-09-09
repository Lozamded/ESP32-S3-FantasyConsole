-- Fin de nivel: detecta contacto del jugador, reproduce "turningon" (un ciclo),
-- al terminar fija "on", le indica al personaje que camine fuera de pantalla
-- (state "finishing") y cambia de escena tras finish_delay segundos.

-- AABB del sprite finish_PC (ajustar segun el asset; origen = ancla del sprite)
local self_x0, self_x1, self_y0, self_y1 = -16, 16, 0, 32
-- AABB del jugador (player.json collision)
local player_x0, player_x1, player_y0, player_y1 = -9, 8, 0, 27

local activated    = false
local switched_on  = false
local timer        = 0.0
local finish_delay = 2.5  -- segundos desde el toque hasta el cambio de escena

-- Variable exportada: editable por instancia en TurtleStudio (Props: sceneToChange = Lvl_2).
local sceneToChange = prop("sceneToChange", "Lvl_2")

local first_frame = true

function _update(dt)
  -- Primer fotograma: contexto de actor ya activo, set_anim es valido aqui.
  if first_frame then
    first_frame = false
    set_anim("off")
    return
  end

  if activated then
    if not switched_on and anim_done() then
      switched_on = true
      set_anim("on")
    end
    timer = timer + dt
    if timer >= finish_delay then
      goto_scene(sceneToChange)
    end
    return
  end

  local player_h = find_by_id("player")
  if not player_h then return end

  local px = obj_posx(player_h)
  local py = obj_posy(player_h)
  local cx = posx()
  local cy = posy()

  local hit = (px + player_x1) > (cx + self_x0) and
              (px + player_x0) < (cx + self_x1) and
              (py + player_y1) > (cy + self_y0) and
              (py + player_y0) < (cy + self_y1)

  if hit then
    activated = true
    play_anim("turningon", 1.0, false)
    state_set("finishing", 1)
  end
end
