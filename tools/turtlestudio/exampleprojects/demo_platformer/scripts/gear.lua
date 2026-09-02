-- Recolectable estatico. Cuando el AABB del jugador solapa con el de esta
-- pieza, se apaga (set_visible false) y suma 1 al contador compartido "gears"
-- (state_add). global.lua lee ese contador en _hud(dt) y actualiza la etiqueta
-- "gearsamount" de la capa GUI "gametstatus".

local collected = false
local player_h = nil

-- AABB propia (objects/Objects/gear.json "collision") y del jugador
-- (character.lua/player.json), relativas a posx/posy de cada actor.
local gear_x0, gear_x1, gear_y0, gear_y1 = -6, 6, -6, 6
local player_x0, player_x1, player_y0, player_y1 = -9, 8, 0, 27

function _update(dt)
  if collected then
    return
  end
  if not player_h then
    player_h = find_by_id("player")
    if not player_h then
      return
    end
  end

  if state_get("defeated") == 1 then return end

  local px = obj_posx(player_h)
  local py = obj_posy(player_h)
  if not px or not py then
    return
  end

  local sx = posx()
  local sy = posy()
  local overlap_x = (sx + gear_x1) > (px + player_x0) and (sx + gear_x0) < (px + player_x1)
  local overlap_y = (sy + gear_y1) > (py + player_y0) and (sy + gear_y0) < (py + player_y1)
  if overlap_x and overlap_y then
    collected = true
    state_add("gears", 1)

    if state_get("gears") > 99 then
      state_add("lifes", 1)
      state_set("gears", 0)
    end

    set_visible(false)
  end
end
