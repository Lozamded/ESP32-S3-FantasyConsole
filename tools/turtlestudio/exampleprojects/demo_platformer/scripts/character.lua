-- Alex Kidd-style controller: walk, jump, simple punch, crouch.
-- Wired to objects/Objects/player.json ("script": "character",
-- animations: idle/walk/jump/fall/attack/air_attack/crouch).
-- Ver spec/lua/physics-v0.md y spec/lua/animation-v0.md.

local walk_speed = 80    -- px/s
local jump_speed = 180   -- px/s (impulso inicial hacia arriba, tambien pico de salto alto)
-- Salto binario: si se suelta A dentro de jump_hold_threshold desde el btnp,
-- vy se recalcula para que el pico coincida exactamente con short_jump_peak
-- (px). Si se mantiene A mas alla del umbral, no hay corte -> salto alto pleno.
-- El calculo saca "cuanta velocidad me falta desde el pico deseado" con
-- v = sqrt(2*g*h_restante), asi el pico corto es constante sin importar en que
-- fotograma exacto de la ventana se solto el boton.
local short_jump_peak = 18      -- px sobre el suelo para el salto corto
local jump_hold_threshold = 0.1 -- s: aguantar A mas alla de esto => salto alto
local gravity = 380      -- px/s^2
local attack_time = 0.25 -- segundos que dura la animacion de golpe

-- Golpe recibido: no hay colision actor-actor en v0 (spec/lua/physics-v0.md
-- "Fuera de alcance"), asi que se detecta con find_by_tag("enemy") + AABB
-- manual (mismo patron que eneny_snake.lua contra directional_block).
-- Los enemigos tienen que llevar la tag "enemy" en la escena para que aparezcan
-- aca.
local damage_time = 0.35   -- s de knockback: sin input, empuje horizontal fijo
local iframes_time = 0.6   -- s de invulnerabilidad tras un golpe (evita re-hit)
local hit_push_speed = 90  -- px/s empuje horizontal opuesto al frente
local hit_pop_speed = 120  -- px/s pequeno impulso vertical al recibir el golpe
local defeat_pop_speed = 132 -- px/s impulso vertical al morir (arco arriba/abajo)
local defeat_time = 2.36     -- s de arco antes de goto_scene
local kill_y = -40           -- Y en espacio escena: caer mas abajo de esto = derrota instantanea

-- AABB de player.json y eneny_snake.json ("collision": {"x0"..."y1"}),
-- relativas a posx()/posy() de cada actor. Duplicadas aca porque Lua no ve el
-- JSON del objeto directamente.
local self_x0, self_x1, self_y0, self_y1 = -9, 8, 0, 27
local enemy_x0, enemy_x1, enemy_y0, enemy_y1 = -6, 7, 0, 13

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
local hurt_timer = 0.0
local iframes_timer = 0.0
local damage_vx = 0.0
local jumping = false  -- true durante la ventana de decision del salto binario
local jump_hold_time = 0.0
local jump_start_y = 0
local defeated = false
local defeat_timer = 0.0
local soul_spawned = false

local hp = 3
state_set("hp", 3)       -- reset al cargar (goto_scene recarga el script, asi hp vuelve a 3)
state_set("defeated", 0) -- idem: gear.lua lo lee para no colectar durante el arco de derrota

local attack_spawned = false

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
  if not attack_spawned then
    attack_spawned = true
    spawn("player_attack", posx(), posy())
  end

  -- Arco de derrota (estilo Mario): sube con impulso, cae con gravedad via set_pos
  -- (sin colision), luego reset de escena. Bloquea todo input y logica normal.
  if defeated then
    defeat_timer = defeat_timer - dt
    local prev_vy = vy
    vy = vy - gravity * dt
    if not soul_spawned and prev_vy >= 0 and vy < 0 then
      soul_spawned = true
      spawn("turtle_soul", posx(), posy()+12, "speed", 52)
    end
    local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
    set_pos(posx(), posy() + my)
    if defeat_timer <= 0.0 then
      local remaining = state_add("lifes", -1)
      if remaining <= 0 then
        goto_scene("game_over")
      else
        restart_scene()
      end
    end
    return
  end

  if posy() < kill_y then
    defeated = true
    defeat_timer = defeat_time
    defeat_pop_speed = 212
    vy = defeat_pop_speed
    flip_h(facing_left)
    flip_v(false)
    play_anim("defeat", 1.0, false)
    state_set("defeated", 1)
    return
  end

  if hurt_timer > 0.0 then hurt_timer = hurt_timer - dt end
  if iframes_timer > 0.0 then iframes_timer = iframes_timer - dt end

  -- Estado de knockback: sin input, empuje fijo, gravedad normal. Sale solo
  -- cuando hurt_timer expira; los iframes siguen contando aparte para tapar
  -- un segundo golpe justo despues.
  if hurt_timer > 0.0 then
    if on_ground() then
      if vy < 0 then vy = 0 end
    else
      vy = vy - gravity * dt
    end
    local mx = math.floor(damage_vx * dt + (damage_vx >= 0 and 0.5 or -0.5))
    local my = math.floor(vy * dt + (vy >= 0 and 0.5 or -0.5))
    local ax, ay = move(mx, my)
    if my > 0 and ay < my then vy = 0 end
    return
  end

  -- Chequeo de golpe recibido: solo si no venimos con iframes activos, tampoco
  -- estamos golpeando (no queremos cancelar attack por un rozamiento del ataque
  -- contra el enemigo, si algun dia hay hitbox de golpe), y NO estamos agachados
  -- (agacharse es una defensa: el enemigo rebota en el jugador, ver eneny_snake.lua).
  -- Nota: `crouching` es el valor del fotograma pasado -- se recalcula despues.
  -- Si sueltas ABAJO justo al chocar, tomarias dano un fotograma despues, no ahora.
  if iframes_timer <= 0.0 and not attacking and not crouching then
    local px = posx()
    local py = posy()
    local enemies = find_by_tag("enemy")
    for i = 1, #enemies do
      -- Un enemigo derrotado por el hitbox del jugador queda cabeza abajo cayendo
      -- (ver eneny_snake.lua). No queremos que ese cadaver siga golpeando al jugador
      -- durante los frames que aun se ve en pantalla, asi que flip_v es la senal
      -- ligera de "esta muerto, ignoralo".
      if not obj_flip_v(enemies[i]) then
        local ex = obj_posx(enemies[i])
        local ey = obj_posy(enemies[i])
        if (px + self_x1) > (ex + enemy_x0) and (px + self_x0) < (ex + enemy_x1) and
           (py + self_y1) > (ey + enemy_y0) and (py + self_y0) < (ey + enemy_y1) then
          damage_vx = facing_left and hit_push_speed or -hit_push_speed
          vy = hit_pop_speed
          rem_x = 0.0
          hurt_timer = damage_time
          iframes_timer = iframes_time
          crouching = false
          was_crouching = false
          cur_anim = "damage"
          play_anim("damage", 1.0, false)
          hp = hp - 1
          state_set("hp", hp)
          if hp <= 0 then
            defeated = true
            play_anim("defeat", 1.0, false)
            defeat_timer = defeat_time
            defeat_pop_speed = 136
            vy = defeat_pop_speed
            flip_h(facing_left)  -- congela direccion horizontal durante el arco
            flip_v(false)        -- congela vertical; previene flip al cruzar pico (vy==0)
            state_set("defeated", 1)
          end
          return
        end
      end
    end
  end

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
      jumping = true
      jump_hold_time = 0.0
      jump_start_y = posy()
    end
  else
    -- Salto binario (dos alturas). Ventana de decision = jump_hold_threshold:
    --  * Se suelta A antes  => vy se recalcula para que el pico sea exactamente
    --    short_jump_peak (fixed, no depende del fotograma exacto de release).
    --  * Se mantiene A hasta pasar la ventana => sin corte, salto alto pleno.
    if jumping then
      jump_hold_time = jump_hold_time + dt
      if jump_hold_time >= jump_hold_threshold then
        jumping = false
      elseif not btn(BTN_A) then
        -- Si height_gained ya paso short_jump_peak (p.ej. rebote de techo), dejamos
        -- vy como este -- forzarlo a 0 aca crearia un "flotado" momentaneo.
        local height_gained = posy() - jump_start_y
        local remaining = short_jump_peak - height_gained
        if remaining > 0 then
          vy = math.sqrt(2 * gravity * remaining)
        end
        jumping = false
      end
    end
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
