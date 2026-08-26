-- Hitbox del golpe del jugador. NO se dibuja: el visual del ataque es la
-- animacion "attack"/"air_attack" del propio jugador (ver character.lua). Este
-- actor solo existe para que otros (los enemigos) puedan consultar posx/posy
-- del hitbox por handle, sin duplicar la geometria de "delante del jugador".
--
-- La senal "hitbox activo" ahora la lee cada enemigo via obj_anim(player)
-- porque set_visible se mantiene siempre en false. La posicion, en cambio, se
-- actualiza SIEMPRE (no solo mientras ataca) -- asi un enemigo puede leer
-- obj_posx/obj_posy del hitbox en el mismo frame en que la animacion cambia a
-- "attack" sin arrastrar coords viejas.

local player_h = nil

-- Distancia horizontal desde el ancla del jugador hasta el ancla del hitbox.
-- El ancla del jugador cae mas o menos en el centro (col_x0=-9, col_x1=8),
-- asi que 12 lo deja justo por delante sin superponerse al torso.
local offset_forward = 12

function _update(dt)
  -- Nunca visible. Igual llamamos set_visible(false) por si el JSON de la
  -- escena termino con visible=true por accidente en una edicion futura.
  set_visible(false)

  if not player_h then
    player_h = find_by_id("player")
    if not player_h then
      return
    end
  end

  local px = obj_posx(player_h)
  local py = obj_posy(player_h)
  if not px or not py then
    return
  end

  local left = obj_flip_h(player_h)
  local dx = left and -offset_forward or offset_forward
  set_pos(px + dx, py)
end
