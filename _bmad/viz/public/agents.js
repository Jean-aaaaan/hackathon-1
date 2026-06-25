// ============================================================
// BMAD Agent Definitions — Habbo/Gather Style Pixel Art
// ============================================================
// Each agent has: metadata, zone assignment, sprite pixel data
// Sprites are 12x16 logical pixels (scaled 3x = 36x48 rendered)
// Colors are indices into each agent's palette
// ============================================================

const PIXEL_SCALE = 3;
const SPRITE_W = 12;
const SPRITE_H = 16;

// Named zones in the room — agents walk to these when active
const ZONES = {
  planning:  { x: 5,  y: 4,  label: 'Planning Corner',  color: 'rgba(91,155,213,0.10)' },
  warRoom:   { x: 18, y: 7,  label: 'War Room',          color: 'rgba(255,215,0,0.08)' },
  design:    { x: 31, y: 4,  label: 'Design Studio',     color: 'rgba(112,173,71,0.10)' },
  security:  { x: 5,  y: 11, label: 'Security Vault',    color: 'rgba(231,76,60,0.10)' },
  qaLab:     { x: 31, y: 11, label: 'QA Lab',            color: 'rgba(237,125,49,0.10)' },
  coding:    { x: 18, y: 16, label: 'Coding Bay',        color: 'rgba(112,173,71,0.10)' },
  ops:       { x: 31, y: 16, label: 'Ops Corner',        color: 'rgba(255,192,0,0.10)' },
  coffee:    { x: 3,  y: 17, label: '',                   color: 'transparent' }, // Rex's hangout
  relax:     { x: 10, y: 20, label: 'Chill Zone',        color: 'rgba(155,89,182,0.10)' },
};

// Room dimensions in tiles
const ROOM_COLS = 38;
const ROOM_ROWS = 22;
const TILE_SIZE = 16; // logical pixels per tile

// Furniture positions (tiles) — impassable for pathfinding
const FURNITURE = [
  // Conference table (center)
  { x: 15, y: 6, w: 7, h: 4, type: 'table' },
  // Coding desk
  { x: 16, y: 15, w: 5, h: 2, type: 'desk' },
  // Whiteboard
  { x: 14, y: 1, w: 10, h: 1, type: 'whiteboard' },
  // Bookshelves
  { x: 1, y: 1, w: 2, h: 1, type: 'bookshelf' },
  { x: 35, y: 1, w: 2, h: 1, type: 'bookshelf' },
  // Plants
  { x: 0, y: 0, w: 1, h: 1, type: 'plant' },
  { x: 37, y: 0, w: 1, h: 1, type: 'plant' },
  { x: 0, y: 21, w: 1, h: 1, type: 'plant' },
  { x: 37, y: 21, w: 1, h: 1, type: 'plant' },
  { x: 27, y: 15, w: 1, h: 1, type: 'plant' },
  // Coffee machine
  { x: 2, y: 17, w: 1, h: 1, type: 'coffee' },
  // Water cooler
  { x: 29, y: 20, w: 1, h: 1, type: 'water' },
  // Bean bags (in chill zone)
  { x: 9, y: 20, w: 1, h: 1, type: 'beanbag' },
  { x: 11, y: 20, w: 1, h: 1, type: 'beanbag' },
  { x: 13, y: 20, w: 1, h: 1, type: 'beanbag' },
  // Monitors at coding bay
  { x: 17, y: 15, w: 1, h: 1, type: 'monitor' },
  { x: 19, y: 15, w: 1, h: 1, type: 'monitor' },
  // Relax room furniture
  { x: 8, y: 19, w: 3, h: 1, type: 'couch' },
  { x: 12, y: 19, w: 1, h: 1, type: 'tv' },
  { x: 14, y: 20, w: 1, h: 1, type: 'snacks' },
];

// ============================================================
// Pixel sprite data for each agent
// Each sprite is a 12x16 grid. 0 = transparent.
// Other numbers map to agent's palette.
// "down" facing (default idle pose)
// ============================================================

function createAgentSprite(skinColor, hairColor, shirtColor, pantsColor, accentColor, hairStyle, extras) {
  // Returns a standardized top-down character sprite
  // hairStyle: 'short', 'bun', 'ponytail', 'spiky', 'long', 'hoodie', 'neat'
  // extras: 'glasses', 'headphones', 'badge', 'scarf', etc.

  const S = skinColor, H = hairColor, T = shirtColor, P = pantsColor, A = accentColor;
  const _ = 0; // transparent

  // Base body template — cute chibi proportions (big head, small body)
  // We customize per agent via colors and hair

  let sprite;

  switch (hairStyle) {
    case 'bun': // Mary — neat bun on top
      sprite = [
        [_,_,_,_,H,H,H,H,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,A,S,S,S,A,S,S,_,_], // eyes (A = glasses if applicable)
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,A,A,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'short': // John, Anand — clean short hair
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,A,S,S,S,A,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'beard': // Winston — tall with beard
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,A,S,S,S,A,S,S,_,_],
        [_,_,S,S,H,H,H,S,S,S,_,_], // beard
        [_,_,_,S,H,H,H,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,A,A,T,T,_,_,_], // vest accent
        [_,_,T,T,T,A,A,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'casual': // Bob — friendly, hoodie style
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,A,S,S,S,A,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'ponytail': // Amelia — headphones + ponytail
      sprite = [
        [_,_,_,_,H,H,H,_,_,_,_,_],
        [_,_,A,H,H,H,H,H,H,A,_,_], // A = headphones
        [_,_,A,H,H,H,H,H,H,A,_,_],
        [_,_,A,S,S,S,S,S,S,A,_,_],
        [_,_,S,S,S,S,S,S,S,S,H,_], // ponytail extends right
        [_,_,S,7,S,S,S,7,S,S,H,_], // 7 = dark eyes
        [_,_,S,S,S,S,S,S,S,S,H,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'creative': // Amanda — colorful streak in hair
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,A,H,H,H,_,_,_], // A = color streak
        [_,_,H,H,A,A,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'glasses': // Thomas — precise, glasses
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,A,7,A,S,A,7,A,S,_,_], // glasses frames around eyes
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_], // lab coat = white/light shirt
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'sharp': // Carol — serious, sharp look
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,A,T,T,A,T,T,_,_], // suit lapels
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'spiky': // Rex — spiky hair, smirk
      sprite = [
        [_,_,H,_,H,_,H,_,H,_,_,_], // spiky
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,7,S,_,_], // smirk (asymmetric)
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_], // red jacket
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'scarf': // Iris — creative with bright scarf
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,A,A,A,A,A,A,_,_,_], // scarf
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'hoodie': // Ethan — hoodie up
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_], // hoodie over head
        [_,_,T,T,H,H,H,H,T,T,_,_],
        [_,_,T,S,S,S,S,S,S,T,_,_],
        [_,_,T,S,S,S,S,S,S,T,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'bookish': // Paige — warm, bookish
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,7,S,S,S,S,_,_], // warm smile
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_], // cardigan
        [_,_,A,T,T,T,T,T,T,A,_,_], // cardigan edges
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'flannel': // Stacey — casual, approachable
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,7,S,S,S,S,_,_], // friendly smile
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,A,T,A,T,T,_,_,_], // flannel pattern
        [_,_,T,A,T,A,T,A,T,T,_,_],
        [_,_,T,T,A,T,A,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'clipboard': // Quinn — methodical, clipboard in hand (accent stripe on shirt)
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,7,S,S,S,S,_,_], // focused expression
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,A,T,T,T,_,_,_], // accent stripe down center
        [_,_,T,T,T,A,T,T,T,T,A,_], // clipboard in right hand
        [_,_,T,T,T,A,T,T,T,T,A,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    case 'neat': // Liam — clean cut, magnifying glass vibe (detail-oriented)
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,A,S,S,S,A,S,S,_,_], // sharp eyes (A = accent for observant look)
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,A,T,T,A,T,T,_,_], // blazer with accent buttons
        [_,_,T,T,T,A,A,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
      break;

    default: // Generic fallback
      sprite = [
        [_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,H,H,H,H,H,H,_,_,_],
        [_,_,H,H,H,H,H,H,H,H,_,_],
        [_,_,H,S,S,S,S,S,S,H,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,S,7,S,S,S,7,S,S,_,_],
        [_,_,S,S,S,S,S,S,S,S,_,_],
        [_,_,_,S,S,S,S,S,S,_,_,_],
        [_,_,_,_,T,T,T,T,_,_,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,T,T,T,T,T,T,T,T,_,_],
        [_,_,_,T,T,T,T,T,T,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,_,P,P,_,_,P,P,_,_,_],
        [_,_,P,P,_,_,_,_,P,P,_,_],
      ];
  }

  return sprite;
}

// ============================================================
// The 16 Agents
// ============================================================

const AGENTS = {
  Mary: {
    name: 'Mary',
    role: 'Analyst',
    layer: 'planning',
    layerColor: '#5B9BD5',
    defaultZone: 'planning',
    walkSpeed: 3.5,
    palette: {
      skin: '#F5D0A9',
      hair: '#5C3317',
      shirt: '#2C3E6B',  // navy blazer
      pants: '#3D3D3D',
      accent: '#8B7355', // glasses
      eyes: '#2C2C2C',
    },
    hairStyle: 'bun',
    idleFidgetChance: 0.02,
  },

  John: {
    name: 'John',
    role: 'Product Manager',
    layer: 'planning',
    layerColor: '#5B9BD5',
    defaultZone: 'planning',
    walkSpeed: 3.8,
    palette: {
      skin: '#D2956A',
      hair: '#1A1A1A',
      shirt: '#4A90D2',  // blue polo
      pants: '#3D4F5F',
      accent: '#4A90D2',
      eyes: '#1A1A1A',
    },
    hairStyle: 'short',
    idleFidgetChance: 0.015,
  },

  Winston: {
    name: 'Winston',
    role: 'Architect',
    layer: 'planning',
    layerColor: '#5B9BD5',
    defaultZone: 'planning',
    walkSpeed: 3.2,
    palette: {
      skin: '#F5D0A9',
      hair: '#4A3728',
      shirt: '#6B7B5E',  // vest
      pants: '#3D3D3D',
      accent: '#8B6914', // vest accent
      eyes: '#2C2C2C',
    },
    hairStyle: 'beard',
    idleFidgetChance: 0.01,
  },

  Bob: {
    name: 'Bob',
    role: 'Scrum Master',
    layer: 'planning',
    layerColor: '#5B9BD5',
    defaultZone: 'warRoom',
    walkSpeed: 4.0,
    palette: {
      skin: '#F0C8A0',
      hair: '#B8860B',
      shirt: '#6A9EC7',  // hoodie
      pants: '#4A5568',
      accent: '#6A9EC7',
      eyes: '#2C2C2C',
    },
    hairStyle: 'casual',
    idleFidgetChance: 0.025,
  },

  Amelia: {
    name: 'Amelia',
    role: 'Developer',
    layer: 'execution',
    layerColor: '#70AD47',
    defaultZone: 'coding',
    walkSpeed: 3.5,
    palette: {
      skin: '#F5D0A9',
      hair: '#2C1810',
      shirt: '#2C2C2C',  // black tee
      pants: '#3D3D5C',
      accent: '#7C8DB0', // headphones
      eyes: '#1A1A1A',
    },
    hairStyle: 'ponytail',
    idleFidgetChance: 0.03,
  },

  Amanda: {
    name: 'Amanda',
    role: 'UI/UX Expert',
    layer: 'execution',
    layerColor: '#70AD47',
    defaultZone: 'design',
    walkSpeed: 3.6,
    palette: {
      skin: '#E8C298',
      hair: '#4A2040',
      shirt: '#5C5C5C',  // turtleneck
      pants: '#3D3D3D',
      accent: '#E855A0', // pink hair streak
      eyes: '#1A1A1A',
    },
    hairStyle: 'creative',
    idleFidgetChance: 0.02,
  },

  Thomas: {
    name: 'Thomas',
    role: 'Quality Strategist',
    layer: 'quality',
    layerColor: '#ED7D31',
    defaultZone: 'qaLab',
    walkSpeed: 3.4,
    palette: {
      skin: '#D2956A',
      hair: '#1A1A1A',
      shirt: '#E8E8E8',  // lab coat
      pants: '#3D4F5F',
      accent: '#7C8DB0', // glasses frames
      eyes: '#1A1A1A',
    },
    hairStyle: 'glasses',
    idleFidgetChance: 0.01,
  },

  Carol: {
    name: 'Carol',
    role: 'Security Architect',
    layer: 'quality',
    layerColor: '#ED7D31',
    defaultZone: 'security',
    walkSpeed: 3.3,
    palette: {
      skin: '#F0C8A0',
      hair: '#1A1A1A',
      shirt: '#2C2C3C',  // dark suit
      pants: '#1A1A2E',
      accent: '#C0C0C0', // silver accents
      eyes: '#1A1A1A',
    },
    hairStyle: 'sharp',
    idleFidgetChance: 0.008,
  },

  Anand: {
    name: 'Anand',
    role: 'CTO / Release',
    layer: 'operations',
    layerColor: '#FFC000',
    defaultZone: 'ops',
    walkSpeed: 3.5,
    palette: {
      skin: '#C68642',
      hair: '#8B8B8B',   // salt-pepper
      shirt: '#4A6B8A',  // button-up
      pants: '#3D3D3D',
      accent: '#4A6B8A',
      eyes: '#1A1A1A',
    },
    hairStyle: 'short',
    idleFidgetChance: 0.012,
  },

  Paige: {
    name: 'Paige',
    role: 'Tech Writer',
    layer: 'execution',
    layerColor: '#70AD47',
    defaultZone: 'design',
    walkSpeed: 3.4,
    palette: {
      skin: '#F5D0A9',
      hair: '#8B4513',
      shirt: '#A0785A',  // cardigan
      pants: '#5C5C5C',
      accent: '#D4A574', // cardigan edges
      eyes: '#2C2C2C',
    },
    hairStyle: 'bookish',
    idleFidgetChance: 0.02,
  },

  Rex: {
    name: 'Rex',
    role: "Devil's Advocate",
    layer: 'adversarial',
    layerColor: '#E74C3C',
    defaultZone: 'coffee',
    walkSpeed: 4.5, // fastest — impatient
    palette: {
      skin: '#F0C8A0',
      hair: '#B22222',   // fiery red
      shirt: '#C0392B',  // red jacket
      pants: '#2C2C2C',
      accent: '#C0392B',
      eyes: '#1A1A1A',
    },
    hairStyle: 'spiky',
    idleFidgetChance: 0.035,
  },

  Iris: {
    name: 'Iris',
    role: 'Design Thinker',
    layer: 'research',
    layerColor: '#9B59B6',
    defaultZone: 'planning',
    walkSpeed: 3.5,
    palette: {
      skin: '#E8C298',
      hair: '#4A2040',
      shirt: '#7B68AE',  // flowy purple top
      pants: '#4A5568',
      accent: '#E8A840', // bright scarf
      eyes: '#1A1A1A',
    },
    hairStyle: 'scarf',
    idleFidgetChance: 0.022,
  },

  Ethan: {
    name: 'Ethan',
    role: 'White Hat Hacker',
    layer: 'adversarial',
    layerColor: '#E74C3C',
    defaultZone: 'security',
    walkSpeed: 3.8,
    palette: {
      skin: '#F0C8A0',
      hair: '#3D2817',
      shirt: '#2C2C2C',  // dark hoodie
      pants: '#1A1A2E',
      accent: '#2C2C2C',
      eyes: '#1A1A1A',
    },
    hairStyle: 'hoodie',
    idleFidgetChance: 0.018,
  },

  Stacey: {
    name: 'Stacey',
    role: 'E2E Tester',
    layer: 'quality',
    layerColor: '#ED7D31',
    defaultZone: 'qaLab',
    walkSpeed: 3.6,
    palette: {
      skin: '#D2956A',
      hair: '#5C3317',
      shirt: '#C75B3A',  // flannel base
      pants: '#4A5568',
      accent: '#E8A840', // flannel pattern
      eyes: '#1A1A1A',
    },
    hairStyle: 'flannel',
    idleFidgetChance: 0.02,
  },

  Quinn: {
    name: 'Quinn',
    role: 'Test Author',
    layer: 'quality',
    layerColor: '#ED7D31',
    defaultZone: 'qaLab',
    walkSpeed: 3.5,
    palette: {
      skin: '#F0C8A0',
      hair: '#6B4226',
      shirt: '#2E8B57',  // forest green polo — methodical, grounded
      pants: '#3D4F5F',
      accent: '#F5F5DC', // clipboard / stripe accent (off-white)
      eyes: '#2C2C2C',
    },
    hairStyle: 'clipboard',
    idleFidgetChance: 0.018,
  },

  Liam: {
    name: 'Liam',
    role: 'Code Reviewer',
    layer: 'quality',
    layerColor: '#ED7D31',
    defaultZone: 'coding',
    walkSpeed: 3.3,
    palette: {
      skin: '#F5D0A9',
      hair: '#2C1810',
      shirt: '#4A4A6A',  // slate blue blazer — professional, detail-oriented
      pants: '#2C2C3C',
      accent: '#C0A060', // gold buttons / observant eye accent
      eyes: '#1A1A1A',
    },
    hairStyle: 'neat',
    idleFidgetChance: 0.012,
  },
};

// Generate sprite data for each agent
for (const [name, agent] of Object.entries(AGENTS)) {
  const p = agent.palette;
  agent.sprite = createAgentSprite(
    p.skin, p.hair, p.shirt, p.pants, p.accent, agent.hairStyle
  );
  // Assign default position (will be updated by zone)
  const zone = ZONES[agent.defaultZone];
  agent.x = zone.x + (Math.random() * 2 - 1) | 0;
  agent.y = zone.y + (Math.random() * 2 - 1) | 0;
  agent.targetX = agent.x;
  agent.targetY = agent.y;
  agent.facing = 'down';
  agent.state = 'idle'; // idle, walking, active, speaking
  agent.walkFrame = 0;
  agent.bobOffset = Math.random() * Math.PI * 2; // stagger idle animations
  agent.speechBubble = null;
  agent.glowAlpha = 0;
  agent.emote = null;
}

// Color lookup: resolve sprite number to actual color
function resolveColor(agent, colorIndex) {
  const p = agent.palette;
  switch (colorIndex) {
    case 0: return null; // transparent
    case 7: return p.eyes;
    default:
      // The sprite uses the actual color values directly
      // Match by comparing to palette values
      if (colorIndex === p.skin) return p.skin;
      if (colorIndex === p.hair) return p.hair;
      if (colorIndex === p.shirt) return p.shirt;
      if (colorIndex === p.pants) return p.pants;
      if (colorIndex === p.accent) return p.accent;
      return colorIndex; // fallback: treat as raw color string
  }
}

// Export everything
window.BMAD = {
  AGENTS,
  ZONES,
  FURNITURE,
  ROOM_COLS,
  ROOM_ROWS,
  TILE_SIZE,
  PIXEL_SCALE,
  SPRITE_W,
  SPRITE_H,
  resolveColor,
};
