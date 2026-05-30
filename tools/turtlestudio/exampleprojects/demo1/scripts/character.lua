-- Plataformero: movimiento, salto, animaciones, flip (spec/lua/physics-v0.md, animation-v0.md)

local walk_speed = 65
local jump_speed = 240
local gravity = 364
local BTN_LEFT, BTN_RIGHT, BTN_A = 0, 1, 4
local rem_x = 0.0
local vy = 0.0
local cur_anim = ""
local facing_left = false

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

  if on_ground() then
    if vy < 0 then
      vy = 0
    end
    if btnp(BTN_A) then
      vy = jump_speed
    end
  else
    vy = vy - gravity * dt
  end

  local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
  move(mx, my)
  update_anim(mx)
end
