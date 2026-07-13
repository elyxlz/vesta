---
name: trivia
description: Run a trivia game with the user. Use when the user says "let's play trivia", "trivia game", "quiz", or asks for trivia questions on a topic. Generates 15 multiple-choice questions easy to hard, marks correct answers, and tallies scores across multiple players.
---

# Trivia

A multi-player trivia game. The user picks a topic, you generate 15 questions on it, and they call out who scores each round. You keep the running tally.

## Default Game Format

- **15 questions per topic, easy to hard**: 5 easy (Q1-Q5), 5 medium (Q6-Q10), 5 hard (Q11-Q15)
- **4 multiple-choice options per question**: A, B, C, D
- **Track scores** across one or more players

## How to Run

1. Ask the user for the topic and the player names (if multiple players).
2. Generate 15 questions. Use the format below.
3. Send all 15 in one message (so they can read aloud). Mark the correct answer on each line.
4. The user calls scores after each question or batch ("Alice 1", "point for Bob", "Carol loses a point", "0.5 for Carol").
5. Update the tally and echo the running scores in short.
6. When the user says "next topic <X>", generate 15 new questions on that topic, preserving the running scores across topics.
7. When the user wraps the game, send the final scoreboard.

## Question Format

```
**Q1 (easy).** Question text here?
A) Option one   B) Option two   C) Option three   D) Option four
→ correct: B
```

For hard questions, include a brief parenthetical note on tricky points (e.g. "→ correct: A (3 titles: 2000, 2002, 2014)").

## Score Tally Format

Always echo scores in a single tight block:

```
Alice: 5
Bob: 3
Carol: 9
```

No commentary unless the round ends or the user asks for context.

## Scoring Conventions

- "point for X" = +1 to X
- "X 1" / "1 point for X" = +1 to X
- "X loses a point" = -1 to X
- "X 2" / "2 for X" / "2 points for X" = +2 to X
- "X 0" = no change to X this round
- "X 0.5" / "X half" = +0.5 to X
- "another .5" with last-mentioned player = +0.5 to that player
- Negative scores allowed. Don't floor at 0.

## Topic Tips

- Suggest some if the user is stuck: sports, food, music, films, geography, history, science, languages.
- Mix question styles: facts, people, places, dates, numbers, definitions, "which of these is..." comparisons.
- Avoid contested or trick questions in the easy band. Save those for hard with a clarifying note.
- If a "fact" is contested (e.g. longest river Nile vs Amazon), either swap the question or note the dispute in the answer.
- Aim for global mix unless the topic is regional.

## When the User Asks To Save / Continue / Reset

- Save the current scoreboard to `/tmp/trivia_scores.txt` if the user wants to pause and resume later.
- Reset means zero everyone out.
