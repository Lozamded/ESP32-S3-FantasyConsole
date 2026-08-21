-- Alex Kidd-style controller: walk, jump, simple punch, crouch.
-- Wired to objects/Objects/player.json ("script": "character",
-- animations: idle/walk/jump/fall/attack/air_attack/crouch).
-- Ver spec/lua/physics-v0.md y spec/lua/animation-v0.md.

local walk_speed = 80    -- px/s
local jump_speed = 180   -- px/s (impulso inicial hacia arriba)
local gravity = 380      -- px/s^2
local attack_time = 0.25 -- segundos que dura la animacion de golpe

local BTN_LEFT, BTN_RIGHT, BTN_DOWN, BTN_A, BTN_B = 0, 1, 3, 4, 5

local rem_x = 0.0
local vy = 0.0
local facing_left = false
local cur_anim = ""
local attacking = false
local attack_in_air = false
local attack_timer = 0.0
local crouching = false
local was_crouching = false

local function set_facing(dx)
  if dx < 0 and not facing_left then
    flip_h(true)
    facing_left = true
  elseif dx > 0 and facing_left then
    flip_h(false)
    facing_left = false
  end
end

local function set_anim_once(anim)
  if anim ~= cur_anim then
    set_anim(anim)
    cur_anim = anim
  end
end

function _update(dt)
  local grounded = on_ground()

  -- Agachado: solo en tierra, sin golpear; se sale al soltar ABAJO.
  crouching = grounded and not attacking and btn(BTN_DOWN)
  if crouching and not was_crouching then
    -- set_anim() siempre deja el loop en true (spec/lua/animation-v0.md); para que
    -- la agachada no repita hay que entrar con play_anim(..., repeat=false), una
    -- sola vez al iniciar (play_anim reinicia el fotograma 0 en cada llamada).
    play_anim("crouch", 1.0, false)
    cur_anim = "crouch"
  end
  was_crouching = crouching

  -- Empezar el golpe: btnp() para que mantener B no lo repita cada fotograma.
  -- No agachado -- no hay animacion de golpe agachado.
  if not attacking and not crouching and btnp(BTN_B) then
    attacking = true
    attack_in_air = not grounded
    attack_timer = attack_time
    cur_anim = attack_in_air and "air_attack" or "attack"
    play_anim(cur_anim, 1.0, false)
  end

  -- En tierra el personaje se planta mientras golpea (como Alex Kidd) o
  -- agachado; en el aire conserva el control horizontal del salto.
  local dx = 0
  if crouching then
    dx = 0
  elseif not attacking or attack_in_air then
    dx = axis(BTN_LEFT, BTN_RIGHT)
  end
  rem_x = rem_x + dx * walk_speed * dt
  local mx = math.floor(rem_x + 0.5)
  if dx ~= 0 then
    set_facing(dx)
  end

  if grounded then
    if vy < 0 then
      vy = 0
    end
    if not attacking and not crouching and btnp(BTN_A) then
      vy = jump_speed
    end
  else
    vy = vy - gravity * dt
  end

  local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
  local ax, ay = move(mx, my)

  -- Sin esto: teletransporte al despejar un choque lateral, o quedar pegado
  -- bajo un techo (ver spec/lua/physics-v0.md, "Bugs comunes al usar move()").
  if ax == mx then
    rem_x = rem_x - ax
  else
    rem_x = 0.0
  end
  if my > 0 and ay < my then
    vy = 0
  end

  if attacking then
    attack_timer = attack_timer - dt
    if attack_timer <= 0.0 then
      attacking = false
    else
      return -- se mantiene la animacion de golpe; no la pise idle/walk/jump/fall.
    end
  end

  if crouching then
    set_anim_once("crouch")
  elseif not on_ground() then
    set_anim_once(vy > 0 and "jump" or "fall")
  elseif dx ~= 0 then
    set_anim_once("walk")
  else
    set_anim_once("idle")
  end
end
