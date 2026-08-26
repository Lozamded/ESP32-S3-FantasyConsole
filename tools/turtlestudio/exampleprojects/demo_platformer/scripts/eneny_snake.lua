-- Patrulla horizontal con gravedad (ver spec/lua/physics-v0.md) para el enemigo
-- "eneny_snake" (objects/Objects/eneny_snake.json, "script": "eneny_snake").
-- Cambia de direccion al tocar un "directional_block" etiquetado "turn" en la
-- escena (find_by_tag, spec/scene-object-identity-v0.md) -- v0 no tiene colision
-- actor-actor real (spec/lua/physics-v0.md "Fuera de alcance"), asi que la
-- deteccion es un chequeo de AABB manual contra los bloques encontrados por tag,
-- no move() chocando contra ellos.
--
-- Derrota: el hitbox del jugador (obj_id "player_attack", ver player_attack.lua)
-- es invisible y solo aporta posx/posy. La senal "el jugador esta atacando"
-- se lee directo de obj_anim(player) == "attack"|"air_attack". Si en ese frame
-- el AABB del hitbox solapa con el del enemigo, entra en modo derrota: sin
-- patrulla, sin colision (set_pos en vez de move), cabeza abajo (flip_v) cayendo
-- por gravedad hasta salir del viewport, momento en el que se apaga (set_visible
-- false) definitivamente. No se resetea -- una vez derrotado, queda derrotado.
--
-- Agachada del jugador: si obj_anim(player) == "crouch" y su AABB solapa con
-- el del enemigo, se trata como pared (el enemigo se da vuelta). En paralelo,
-- character.lua salta el chequeo de dano cuando `crouching` esta activo, asi
-- que agacharse frena tanto al enemigo como al golpe.

local walk_speed = 30    -- px/s
local gravity = 420      -- px/s^2 (igual que scripts/character.lua)
local defeat_fall_gravity = 220  -- caida mas lenta que gravity normal para que se vea la muerte
local defeat_kill_y = -40         -- por debajo de este y, apagar el actor
local vy = 0.0
local dir = 1             -- 1 = derecha, -1 = izquierda
local defeated = false
local hitbox_h = nil
local player_h = nil

-- AABB de colision (objects/Objects/eneny_snake.json y directional_block.json,
-- "collision": {"x0":..,"x1":..}), relativas a posx() de cada actor.
local snake_x0, snake_x1 = -6, 7
local snake_y0, snake_y1 = 0, 13

-- Bounds de sprite del hitbox del jugador (objects/Sprites/player_attack.json:
-- pixel_w=8, pixel_h=24, origin_x=4, origin_y=0). No hay "collision" en
-- player_attack.json, asi que el rect visible del sprite es el hitbox real.
local hit_x0, hit_x1 = -4, 3
local hit_y0, hit_y1 = 0, 23

-- AABB del jugador (character.lua/player.json), relativos a su posx/posy.
-- Usado para el rebote-por-agachada: si el jugador esta agachado y el enemigo
-- lo toca, cambia de direccion en vez de darle dano al jugador.
local player_x0, player_x1 = -9, 8
local player_y0, player_y1 = 0, 27

local block_x0, block_x1 = 0, 15

local function check_hitbox_kill(sx, sy)
  if not player_h then
    player_h = find_by_id("player")
    if not player_h then
      return false
    end
  end
  local anim = obj_anim(player_h)
  if anim ~= "attack" and anim ~= "air_attack" then
    return false
  end
  if not hitbox_h then
    hitbox_h = find_by_id("player_attack")
    if not hitbox_h then
      return false
    end
  end
  local hx = obj_posx(hitbox_h)
  local hy = obj_posy(hitbox_h)
  if not hx or not hy then
    return false
  end
  return (sx + snake_x1) > (hx + hit_x0) and (sx + snake_x0) < (hx + hit_x1) and
         (sy + snake_y1) > (hy + hit_y0) and (sy + snake_y0) < (hy + hit_y1)
end

function _update(dt)
  if defeated then
    -- Caida libre sin colision. set_pos no toca `grounded` ni resuelve tiles: el
    -- cadaver pasa a traves de plataformas y sale por abajo.
    vy = vy - defeat_fall_gravity * dt
    local ny = posy() + math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
    if ny <= defeat_kill_y then
      set_visible(false)
      -- Congelar la posicion para no seguir descendiendo eternamente aunque el
      -- actor este oculto -- las _update siguen corriendo aunque no se dibuje.
      set_pos(posx(), defeat_kill_y)
      vy = 0.0
      return
    end
    set_pos(posx(), ny)
    return
  end

  local sx = posx()
  local sy = posy()
  if check_hitbox_kill(sx, sy) then
    defeated = true
    flip_v(true)
    vy = 60.0  -- pequeno pop hacia arriba antes de la caida, tipo enemigo derrotado clasico
    return
  end

  if on_ground() then
    vy = 0.0
  else
    vy = vy - gravity * dt
  end
  local mx = math.floor(dir * walk_speed * dt + 0.5)
  local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
  local ax = move(mx, my)

  -- Un solo flip por fotograma: si el tile solido ya bloqueo, no volvemos a
  -- consultar los bloques "turn" -- si no, un bloque a la espalda con overlap
  -- en X invertiria la direccion recien puesta y el enemigo oscilaria pegado
  -- a la pared.
  local should_flip = false

  if mx ~= 0 and ax == 0 then
    should_flip = true
  else
    local blocks = find_by_tag("turn")
    for i = 1, #blocks do
      local bx = obj_posx(blocks[i])
      local overlap = (sx + snake_x1) > (bx + block_x0) and (sx + snake_x0) < (bx + block_x1)
      if overlap then
        -- Solo invertir si nos estabamos acercando -- si no, seguiriamos
        -- viendo overlap varios fotogramas al alejarnos y oscilariamos.
        local approaching = (dir > 0 and bx > sx) or (dir < 0 and bx < sx)
        if approaching then
          should_flip = true
        end
        break
      end
    end
  end

  -- Rebote por jugador agachado: la agachada es defensa. Si el jugador esta en
  -- animacion "crouch" y su AABB solapa con el del enemigo, se trata como una
  -- pared (el enemigo se da vuelta). character.lua ya gate-ea el dano por
  -- crouching, asi que en la practica los dos scripts se retroalimentan.
  if not should_flip and player_h then
    if obj_anim(player_h) == "crouch" then
      local px = obj_posx(player_h)
      local py = obj_posy(player_h)
      if px and py then
        local overlap_x = (sx + snake_x1) > (px + player_x0) and (sx + snake_x0) < (px + player_x1)
        local overlap_y = (sy + snake_y1) > (py + player_y0) and (sy + snake_y0) < (py + player_y1)
        if overlap_x and overlap_y then
          local approaching = (dir > 0 and px > sx) or (dir < 0 and px < sx)
          if approaching then
            should_flip = true
          end
        end
      end
    end
  end

  if should_flip then
    dir = -dir
    flip_h(dir < 0)
  end
end
