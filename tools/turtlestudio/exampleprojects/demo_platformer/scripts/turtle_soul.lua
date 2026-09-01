-- Alma del personaje: sube constantemente sin colision tras la derrota.
local rise_speed = 52  -- px/s hacia arriba

function _update(dt)
  local my = math.floor(rise_speed * dt + 0.5)
  set_pos(posx(), posy() + my)
end
