import './style.css'
import {
  COLS,
  createEmptyBoard,
  dropPiece,
  type Board,
  type Player,
  type ResolvedMove,
} from './game'
const CELL_SIZE = 68
const CELL_GAP = 8
const DROP_ANIMATION_MS = 360

const PLAYER_LABELS: Record<Player, string> = {
  1: 'Red',
  2: 'Yellow',
}

const appRoot = document.querySelector<HTMLDivElement>('#app')

if (!appRoot) {
  throw new Error('App root not found')
}
const app: HTMLDivElement = appRoot

let board: Board = createEmptyBoard()
let currentPlayer: Player = 1
let winner: Player | null = null
let isDraw = false
let isAnimating = false
let animatedCell: { row: number; col: number } | null = null
let pendingMove: ResolvedMove | null = null

render()

function render(): void {
  const status = getStatusText()
  const isGameOver = winner !== null || isDraw

  app.innerHTML = `
    <main class="page">
      <section class="game-shell" aria-label="Connect 4 game">
        <header class="game-header">
          <h1>Connect 4</h1>
          <p class="status">${status}</p>
        </header>

        <div class="board-wrapper">
          <div class="column-controls" role="group" aria-label="Choose a column">
            ${Array.from({ length: COLS }, (_, col) => {
              const disabled =
                isGameOver || isAnimating || board[0][col] !== 0 ? 'disabled' : ''

              return `
                <button
                  class="column-hit"
                  data-col="${col}"
                  aria-label="Drop piece in column ${col + 1}"
                  ${disabled}
                >
                  <span>${col + 1}</span>
                </button>
              `
            }).join('')}
          </div>

          <div class="board" role="grid" aria-label="Connect 4 board">
            ${board
              .map((row, rowIndex) =>
                row
                  .map((cell, colIndex) => {
                    const playerClass = cell === 0 ? 'empty' : `player-${cell}`
                    const shouldAnimate =
                      animatedCell?.row === rowIndex && animatedCell?.col === colIndex
                    const animateClass = shouldAnimate ? 'dropping' : ''
                    const dropDistance = `${(rowIndex + 1) * (CELL_SIZE + CELL_GAP)}px`

                    return `
                      <div class="slot" role="gridcell" aria-label="Row ${rowIndex + 1}, Column ${colIndex + 1}">
                        <div class="disc ${playerClass} ${animateClass}" style="--drop-distance: ${dropDistance}"></div>
                      </div>
                    `
                  })
                  .join(''),
              )
              .join('')}
          </div>
        </div>

        <footer class="controls">
          <button class="reset-btn" type="button" id="reset-game">Restart Game</button>
        </footer>
      </section>
    </main>
  `

  app.querySelectorAll<HTMLButtonElement>('.column-hit').forEach((button) => {
    button.addEventListener('click', () => {
      const col = Number(button.dataset.col)
      if (!Number.isNaN(col)) {
        handleDrop(col)
      }
    })
  })

  app.querySelector<HTMLButtonElement>('#reset-game')?.addEventListener('click', resetGame)
}

function getStatusText(): string {
  if (winner) {
    return `${PLAYER_LABELS[winner]} wins!`
  }

  if (isDraw) {
    return "It's a draw."
  }

  if (isAnimating) {
    return `${PLAYER_LABELS[currentPlayer]} piece is dropping...`
  }

  return `${PLAYER_LABELS[currentPlayer]}'s turn`
}

function handleDrop(col: number): void {
  if (winner || isDraw || isAnimating) {
    return
  }

  const move = dropPiece(board, currentPlayer, col)
  if (!move) {
    return
  }

  pendingMove = move
  isAnimating = true
  animatedCell = { row: move.row, col: move.col }
  render()

  window.setTimeout(() => {
    isAnimating = false
    animatedCell = null

    if (!pendingMove) {
      render()
      return
    }

    winner = pendingMove.winner
    isDraw = pendingMove.isDraw

    if (!winner && !isDraw) {
      currentPlayer = pendingMove.nextPlayer
    }

    pendingMove = null
    render()
  }, DROP_ANIMATION_MS)
}

function resetGame(): void {
  board = createEmptyBoard()
  currentPlayer = 1
  winner = null
  isDraw = false
  isAnimating = false
  animatedCell = null
  pendingMove = null
  render()
}
