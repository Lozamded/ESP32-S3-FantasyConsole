
local walk_speed = 75
local jump_speed = 164
local gravity = 364
local BTN_LEFT, BTN_RIGHT, BTN_A = 0, 1, 4
local rem_x = 0.0
local vy = 0.0
local cur_anim = ""
local facing_left = false
local jumping = false
local jump_hold_time = 0.0
local max_jump_hold = 0.18  -- segundos hasta salto "grande"
local low_gravity_factor = 0.4  -- gravedad reducida mientras mantienes A
local coyote_time_max = 0.08
local coyote_time = 0.0

local function dir_axis(neg_btn, pos_btn)
  local v = 0
  if btn(neg_btn) then
    v = v - 1
  end
  if btn(pos_btn) then
    v = v + 1
  end
  return v
end

local function update_facing(mx)
  if mx < 0 then
    if not facing_left then
      flip_h(true)
      facing_left = true
    end
  elseif mx > 0 then
    if facing_left then
      flip_h(false)
      facing_left = false
    end
  end
end

local function update_anim(mx)
  local next_anim = "idle"
  if not on_ground() then
    if vy > 0 then
      next_anim = "jump"
    else
      next_anim = "fall"
    end
  elseif mx ~= 0 then
    next_anim = "walk"
  end

  if next_anim ~= cur_anim then
    set_anim(next_anim)
    cur_anim = next_anim
  end
end

function _update(dt)
  local dx = dir_axis(BTN_LEFT, BTN_RIGHT)

  rem_x = rem_x + dx * walk_speed * dt
  local mx = math.floor(rem_x + 0.5)
  if mx ~= 0 then
    rem_x = rem_x - mx
  end

  update_facing(mx)

  -- Consumir btnp siempre (evita saltos "latched").
  local jump_pressed = btnp(BTN_A)
  local jump_held = btn(BTN_A)
  local grounded = on_ground()

  if grounded then
    coyote_time = coyote_time_max
  else
    coyote_time = math.max(0.0, coyote_time - dt)
  end

  if grounded then
    jumping = false
    jump_hold_time = 0.0
    if vy < 0 then
      vy = 0
    end
    if jump_pressed then
      vy = jump_speed
      jumping = true
      jump_hold_time = 0.0
      coyote_time = 0.0
    end
  else
    if jump_pressed and coyote_time > 0.0 then
      vy = jump_speed
      jumping = true
      jump_hold_time = 0.0
      coyote_time = 0.0
    end
    if jumping and vy > 0 and jump_held and jump_hold_time < max_jump_hold then
      -- Mientras mantienes A y sigues subiendo: gravedad reducida -> salto mas alto.
      vy = vy - gravity * low_gravity_factor * dt
      jump_hold_time = jump_hold_time + dt
    else
      -- Sueltas A pronto o ya llegaste al tope: gravedad normal, salto corto.
      jumping = false
      vy = vy - gravity * dt
    end
  end

  local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
  move(mx, my)
  update_anim(mx)
end
