import { useEffect, useRef } from "react";
import { orbColors, type OrbVisualState } from "./styles";

interface OrbProps {
  state: OrbVisualState;
  size?: number;
  enableTracking?: boolean;
  suppressMotion?: boolean;
}

const LIVE_STATES = new Set<OrbVisualState>([
  "alive",
  "thinking",
  "booting",
  "authenticating",
  "starting",
  "loading",
]);

const COLOR_LERP_SPEED = 3;
const VALUE_LERP_SPEED = 4;
const TRACK_LERP_SPEED = 7;
const FLOAT_LERP_SPEED = 5;
const MAX_FRAME_TIME = 0.05;

const VERTEX_SHADER_SOURCE = `
attribute vec2 a_position;
varying vec2 v_uv;

void main() {
  v_uv = (a_position + 1.0) * 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER_SOURCE = `
precision mediump float;

varying vec2 v_uv;

uniform vec2 u_resolution;
uniform vec3 u_light_color;
uniform vec3 u_mid_color;
uniform vec3 u_dark_color;
uniform vec2 u_track;
uniform vec2 u_highlight;
uniform float u_glow_opacity;
uniform float u_glow_scale;
uniform float u_orb_scale;
uniform float u_scene_scale;
uniform float u_float_offset;

void main() {
  vec2 uv = v_uv * 2.0 - 1.0;
  uv.x *= u_resolution.x / u_resolution.y;

  vec2 center = vec2(
    u_track.x * 0.08 * u_scene_scale,
    u_track.y * 0.08 * u_scene_scale + u_float_offset
  );
  float sphere_radius = 0.58 * u_scene_scale * u_orb_scale;
  float glow_radius = sphere_radius * (1.6 * u_glow_scale);
  float distance_to_center = length(uv - center);

  float glow = exp(-pow(distance_to_center / max(glow_radius, 0.001), 2.0) * 2.6) * u_glow_opacity;
  float orb_mask = 1.0 - smoothstep(sphere_radius - 0.01, sphere_radius + 0.01, distance_to_center);

  vec3 color = u_mid_color * glow * 0.9;
  float alpha = glow;

  if (orb_mask > 0.0) {
    vec2 sphere_uv = (uv - center) / sphere_radius;
    float sphere_depth = sqrt(max(0.0, 1.0 - dot(sphere_uv, sphere_uv)));
    vec3 normal = normalize(vec3(sphere_uv, sphere_depth));
    vec3 light_direction = normalize(vec3(-0.55 + u_track.x * 0.25, -0.75 + u_track.y * 0.25, 1.35));
    float diffuse = max(dot(normal, light_direction), 0.0);
    float fresnel = pow(1.0 - max(normal.z, 0.0), 2.6);
    float shade = clamp(0.22 + diffuse * 0.95, 0.0, 1.0);

    vec3 sphere_color = mix(u_dark_color, u_light_color, shade);
    sphere_color = mix(sphere_color, u_mid_color, 0.22 + (1.0 - diffuse) * 0.18);
    sphere_color *= 1.0 - fresnel * 0.28;

    vec2 highlight_center = center + vec2(
      (-0.18 + u_highlight.x * 0.08) * u_scene_scale * u_orb_scale,
      (-0.24 + u_highlight.y * 0.08) * u_scene_scale * u_orb_scale
    );
    vec2 highlight_delta = uv - highlight_center;
    highlight_delta.x /= 0.38 * u_scene_scale * u_orb_scale;
    highlight_delta.y /= 0.26 * u_scene_scale * u_orb_scale;
    float highlight = exp(-dot(highlight_delta, highlight_delta) * 2.6) * 0.35;

    color += sphere_color + vec3(highlight);
    alpha = max(alpha, orb_mask);
  }

  gl_FragColor = vec4(color, clamp(alpha, 0.0, 1.0));
}
`;

interface VisualTarget {
  lightColor: [number, number, number];
  midColor: [number, number, number];
  darkColor: [number, number, number];
  glowOpacityBase: number;
  glowOpacityAmplitude: number;
  glowScaleBase: number;
  glowScaleAmplitude: number;
  orbScaleBase: number;
  orbScaleAmplitude: number;
  pulseDuration: number;
  floatAmplitudePx: number;
  floatDuration: number;
}

interface VisualState {
  lightColor: [number, number, number];
  midColor: [number, number, number];
  darkColor: [number, number, number];
  glowOpacity: number;
  glowScale: number;
  orbScale: number;
  floatAmplitudePx: number;
  trackX: number;
  trackY: number;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function mix(current: number, target: number, amount: number) {
  return current + (target - current) * amount;
}

function parseRgbColor(value: string): [number, number, number] {
  const channels = (value.match(/[\d.]+/g) ?? [])
    .slice(0, 3)
    .map((channel) => Number.parseFloat(channel) / 255);

  if (channels.length !== 3 || channels.some((channel) => Number.isNaN(channel))) {
    return [1, 1, 1];
  }

  return channels as [number, number, number];
}

function resolveCssColor(value: string, container: HTMLElement) {
  const probe = document.createElement("span");
  probe.style.color = value;
  probe.style.position = "absolute";
  probe.style.visibility = "hidden";
  probe.style.pointerEvents = "none";
  container.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  probe.remove();
  return parseRgbColor(resolved);
}

function createShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
) {
  const shader = gl.createShader(type);

  if (!shader) {
    return null;
  }

  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    return shader;
  }

  gl.deleteShader(shader);
  return null;
}

function createProgram(gl: WebGLRenderingContext) {
  const vertexShader = createShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER_SOURCE);
  const fragmentShader = createShader(
    gl,
    gl.FRAGMENT_SHADER,
    FRAGMENT_SHADER_SOURCE,
  );

  if (!vertexShader || !fragmentShader) {
    if (vertexShader) gl.deleteShader(vertexShader);
    if (fragmentShader) gl.deleteShader(fragmentShader);
    return null;
  }

  const program = gl.createProgram();

  if (!program) {
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);
    return null;
  }

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  gl.deleteShader(vertexShader);
  gl.deleteShader(fragmentShader);

  if (gl.getProgramParameter(program, gl.LINK_STATUS)) {
    return program;
  }

  gl.deleteProgram(program);
  return null;
}

function getVisualTarget(
  state: OrbVisualState,
  container: HTMLElement,
  suppressMotion: boolean,
): VisualTarget {
  const [lightColor, midColor, darkColor] = orbColors[state].map((color) =>
    resolveCssColor(color, container),
  ) as [VisualTarget["lightColor"], VisualTarget["midColor"], VisualTarget["darkColor"]];
  const isLive = LIVE_STATES.has(state);

  if (suppressMotion) {
    return {
      lightColor,
      midColor,
      darkColor,
      glowOpacityBase: state === "thinking" ? 0.55 : isLive ? 0.5 : 0.12,
      glowOpacityAmplitude: 0,
      glowScaleBase: state === "thinking" ? 1.08 : isLive ? 1.04 : 0.85,
      glowScaleAmplitude: 0,
      orbScaleBase: state === "thinking" ? 1.015 : 1,
      orbScaleAmplitude: 0,
      pulseDuration: 2.5,
      floatAmplitudePx: 0,
      floatDuration: state === "thinking" ? 3 : 4,
    };
  }

  return {
    lightColor,
    midColor,
    darkColor,
    glowOpacityBase: state === "thinking" ? 0.55 : isLive ? 0.5 : 0.12,
    glowOpacityAmplitude: state === "thinking" ? 0.08 : 0,
    glowScaleBase: state === "thinking" ? 1.08 : isLive ? 1.04 : 0.85,
    glowScaleAmplitude: state === "thinking" ? 0.028 : 0,
    orbScaleBase: state === "thinking" ? 1.015 : 1,
    orbScaleAmplitude: state === "thinking" ? 0.009 : 0,
    pulseDuration: 2.5,
    floatAmplitudePx: isLive ? (state === "thinking" ? 4 : 3) : 0,
    floatDuration: state === "thinking" ? 3.8 : 5,
  };
}

function createInitialVisualState(target: VisualTarget): VisualState {
  return {
    lightColor: [...target.lightColor] as [number, number, number],
    midColor: [...target.midColor] as [number, number, number],
    darkColor: [...target.darkColor] as [number, number, number],
    glowOpacity: target.glowOpacityBase,
    glowScale: target.glowScaleBase,
    orbScale: target.orbScaleBase,
    floatAmplitudePx: target.floatAmplitudePx,
    trackX: 0,
    trackY: 0,
  };
}

export function Orb({ state, size = 140, enableTracking = false, suppressMotion = false }: OrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isLive = LIVE_STATES.has(state);
  const shouldTrack = enableTracking && isLive;
  const targetTrackRef = useRef({ x: 0, y: 0 });
  const targetVisualRef = useRef<VisualTarget | null>(null);
  const visualStateRef = useRef<VisualState | null>(null);
  const glowColor = orbColors[state][1];
  const glowOpacity = state === "thinking" ? 0.62 : isLive ? 0.46 : 0.18;
  const glowSize = state === "thinking" ? 1.25 : 1.12;
  const glowInset = Math.round(size * 0.18);

  useEffect(() => {
    const container = containerRef.current;

    if (!container) {
      return;
    }

    const target = getVisualTarget(state, container, suppressMotion);
    targetVisualRef.current = target;

    if (!visualStateRef.current) {
      visualStateRef.current = createInitialVisualState(target);
    }
  }, [state, suppressMotion]);

  useEffect(() => {
    if (!shouldTrack) {
      targetTrackRef.current = { x: 0, y: 0 };
      return;
    }

    const onMove = (e: MouseEvent) => {
      const container = containerRef.current;

      if (!container) {
        return;
      }

      const rect = container.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      targetTrackRef.current = {
        x: clamp((e.clientX - cx) / (window.innerWidth * 0.4), -1, 1),
        y: clamp((e.clientY - cy) / (window.innerHeight * 0.4), -1, 1),
      };
    };

    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [shouldTrack]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;

    if (!canvas || !container) {
      return;
    }

    const gl =
      canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        premultipliedAlpha: true,
      }) ?? canvas.getContext("experimental-webgl");

    if (!gl || !(gl instanceof WebGLRenderingContext)) {
      return;
    }

    const program = createProgram(gl);

    if (!program) {
      return;
    }

    const positionLocation = gl.getAttribLocation(program, "a_position");
    const resolutionLocation = gl.getUniformLocation(program, "u_resolution");
    const lightColorLocation = gl.getUniformLocation(program, "u_light_color");
    const midColorLocation = gl.getUniformLocation(program, "u_mid_color");
    const darkColorLocation = gl.getUniformLocation(program, "u_dark_color");
    const trackLocation = gl.getUniformLocation(program, "u_track");
    const highlightLocation = gl.getUniformLocation(program, "u_highlight");
    const glowOpacityLocation = gl.getUniformLocation(program, "u_glow_opacity");
    const glowScaleLocation = gl.getUniformLocation(program, "u_glow_scale");
    const orbScaleLocation = gl.getUniformLocation(program, "u_orb_scale");
    const sceneScaleLocation = gl.getUniformLocation(program, "u_scene_scale");
    const floatOffsetLocation = gl.getUniformLocation(program, "u_float_offset");
    const buffer = gl.createBuffer();

    if (
      positionLocation < 0 ||
      !resolutionLocation ||
      !lightColorLocation ||
      !midColorLocation ||
      !darkColorLocation ||
      !trackLocation ||
      !highlightLocation ||
      !glowOpacityLocation ||
      !glowScaleLocation ||
      !orbScaleLocation ||
      !sceneScaleLocation ||
      !floatOffsetLocation ||
      !buffer
    ) {
      if (buffer) gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      return;
    }

    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([
        -1, -1,
        1, -1,
        -1, 1,
        -1, 1,
        1, -1,
        1, 1,
      ]),
      gl.STATIC_DRAW,
    );

    gl.useProgram(program);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.enableVertexAttribArray(positionLocation);
    gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0);

    const initialTarget =
      targetVisualRef.current ?? getVisualTarget(state, container, suppressMotion);
    targetVisualRef.current = initialTarget;
    visualStateRef.current ??= createInitialVisualState(initialTarget);

    let animationFrame = 0;
    let lastFrameTime = performance.now();

    const render = (frameTime: number) => {
      const visualState = visualStateRef.current;
      const visualTarget = targetVisualRef.current;

      if (!visualState || !visualTarget) {
        animationFrame = window.requestAnimationFrame(render);
        return;
      }

      const deltaTime = Math.min(
        MAX_FRAME_TIME,
        (frameTime - lastFrameTime) / 1000,
      );
      lastFrameTime = frameTime;

      const colorAmount = 1 - Math.exp(-deltaTime * COLOR_LERP_SPEED);
      const valueAmount = 1 - Math.exp(-deltaTime * VALUE_LERP_SPEED);
      const trackAmount = 1 - Math.exp(-deltaTime * TRACK_LERP_SPEED);
      const floatAmount = 1 - Math.exp(-deltaTime * FLOAT_LERP_SPEED);
      const pulseWave = Math.sin(
        (frameTime / 1000 / visualTarget.pulseDuration) * Math.PI * 2,
      );
      const glowOpacityTarget =
        visualTarget.glowOpacityBase +
        visualTarget.glowOpacityAmplitude * pulseWave;
      const glowScaleTarget =
        visualTarget.glowScaleBase +
        visualTarget.glowScaleAmplitude * pulseWave;
      const orbScaleTarget =
        visualTarget.orbScaleBase + visualTarget.orbScaleAmplitude * pulseWave;

      for (let index = 0; index < 3; index += 1) {
        visualState.lightColor[index] = mix(
          visualState.lightColor[index],
          visualTarget.lightColor[index],
          colorAmount,
        );
        visualState.midColor[index] = mix(
          visualState.midColor[index],
          visualTarget.midColor[index],
          colorAmount,
        );
        visualState.darkColor[index] = mix(
          visualState.darkColor[index],
          visualTarget.darkColor[index],
          colorAmount,
        );
      }

      visualState.glowOpacity = mix(
        visualState.glowOpacity,
        glowOpacityTarget,
        valueAmount,
      );
      visualState.glowScale = mix(
        visualState.glowScale,
        glowScaleTarget,
        valueAmount,
      );
      visualState.orbScale = mix(
        visualState.orbScale,
        orbScaleTarget,
        valueAmount,
      );
      visualState.floatAmplitudePx = mix(
        visualState.floatAmplitudePx,
        visualTarget.floatAmplitudePx,
        floatAmount,
      );
      visualState.trackX = mix(
        visualState.trackX,
        targetTrackRef.current.x,
        trackAmount,
      );
      visualState.trackY = mix(
        visualState.trackY,
        targetTrackRef.current.y,
        trackAmount,
      );

      const devicePixelRatio = window.devicePixelRatio || 1;
      const glowPad = Math.round(size * 0.25);
      const renderSize = size + glowPad * 2;
      const canvasWidth = Math.max(1, Math.round(renderSize * devicePixelRatio));
      const canvasHeight = Math.max(1, Math.round(renderSize * devicePixelRatio));

      if (canvas.width !== canvasWidth || canvas.height !== canvasHeight) {
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
        gl.viewport(0, 0, canvasWidth, canvasHeight);
      }

      const floatOffset =
        Math.sin((frameTime / 1000 / visualTarget.floatDuration) * Math.PI * 2) *
        ((visualState.floatAmplitudePx * 2) / renderSize);
      const sceneScale = size / renderSize;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);

      gl.uniform2f(resolutionLocation, canvasWidth, canvasHeight);
      gl.uniform3fv(lightColorLocation, visualState.lightColor);
      gl.uniform3fv(midColorLocation, visualState.midColor);
      gl.uniform3fv(darkColorLocation, visualState.darkColor);
      gl.uniform2f(trackLocation, visualState.trackX, visualState.trackY);
      gl.uniform2f(
        highlightLocation,
        visualState.trackX * 0.6,
        visualState.trackY * 0.6,
      );
      gl.uniform1f(glowOpacityLocation, visualState.glowOpacity);
      gl.uniform1f(glowScaleLocation, visualState.glowScale);
      gl.uniform1f(orbScaleLocation, visualState.orbScale);
      gl.uniform1f(sceneScaleLocation, sceneScale);
      gl.uniform1f(floatOffsetLocation, floatOffset);
      gl.drawArrays(gl.TRIANGLES, 0, 6);

      animationFrame = window.requestAnimationFrame(render);
    };

    animationFrame = window.requestAnimationFrame(render);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, [size, state]);

  return (
    <div
      ref={containerRef}
      style={{ width: size, height: size, position: "relative" }}
    >
      <div
        style={{
          position: "absolute",
          inset: -glowInset,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${glowColor} 0%, transparent 68%)`,
          filter: `blur(${Math.round(size * 0.18)}px)`,
          opacity: glowOpacity,
          transform: `scale(${glowSize})`,
          pointerEvents: "none",
          transition:
            "background 1.5s ease-in-out, opacity 1.5s ease-in-out, transform 1.5s ease-in-out",
        }}
      />
      <canvas
        ref={canvasRef}
        style={{
          width: size + Math.round(size * 0.5),
          height: size + Math.round(size * 0.5),
          display: "block",
          position: "absolute",
          left: -Math.round(size * 0.25),
          top: -Math.round(size * 0.25),
          pointerEvents: "none",
        }}
      />
    </div>
  );
}
