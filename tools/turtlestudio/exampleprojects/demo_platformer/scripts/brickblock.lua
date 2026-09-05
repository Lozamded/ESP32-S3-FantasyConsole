-- Bloque destruible estilo Alex Kidd/Mario: solido para el jugador ("solid":true
-- en el JSON, move() lo ve como pared). Al recibir un golpe del jugador (BTN_B)
-- llama set_solid(false), reproduce la animacion "break" y desaparece. No resetea:
-- una vez destruido, queda invisible.

-- Duracion de la animacion "break" (block_break: 3 fotogramas a 8 fps = 0.375s).
local break_time = 0.5

local breaking  = false
local break_timer = 0.0
local destroyed = false

local player_h  = nil
local hitbox_h  = nil

-- AABB propia (brickblock.json "collision"), relativa a posx()/posy().
-- Solo se usa para detectar el golpe del jugador; la colision fisica la maneja
-- el firmware via "solid":true + actor_aabb_hits_solid_actors en move().
local self_x0, self_x1 = 0, 15
local self_y0, self_y1 = 0, 15

-- Bounds del hitbox del jugador (objects/Sprites/player_attack.json:
-- pixel_w=8, pixel_h=24, origin_x=4, origin_y=0 -- igual que eneny_snake.lua).
local hit_x0, hit_x1 = -4, 3
local hit_y0, hit_y1 = 0, 23

local function resolve_handles()
  if not player_h then player_h = find_by_id("player") end
  if not hitbox_h then hitbox_h = find_by_id("player_attack") end
  return player_h ~= nil and hitbox_h ~= nil
end

local function check_attack_hit(sx, sy)
  if not resolve_handles() then return false end
  local anim = obj_anim(player_h)
  if anim ~= "attack" and anim ~= "air_attack" then return false end
  local hx = obj_posx(hitbox_h)
  local hy = obj_posy(hitbox_h)
  if not hx or not hy then return false end
  return (sx + self_x1) > (hx + hit_x0) and (sx + self_x0) < (hx + hit_x1) and
         (sy + self_y1) > (hy + hit_y0) and (sy + self_y0) < (hy + hit_y1)
end

function _update(dt)
  if destroyed then return end

  if breaking then
    break_timer = break_timer - dt
    if break_timer <= 0.0 then
      destroyed = true
      set_pos(-9999, -9999)
      set_visible(false)
    end
    return
  end

  if check_attack_hit(posx(), posy()) then
    breaking = true
    break_timer = break_time
    set_solid(false)
    play_anim("break", 1.0, false)
  end
end
