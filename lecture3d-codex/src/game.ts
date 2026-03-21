export type Player = 1 | 2
export type BoardCell = 0 | Player
export type Board = BoardCell[][]

export const ROWS = 6
export const COLS = 7

export interface ResolvedMove {
  row: number
  col: number
  winner: Player | null
  isDraw: boolean
  nextPlayer: Player
}

export function createEmptyBoard(): Board {
  return Array.from({ length: ROWS }, () => Array<BoardCell>(COLS).fill(0))
}

export function findOpenRow(board: Board, col: number): number | null {
  for (let row = ROWS - 1; row >= 0; row -= 1) {
    if (board[row][col] === 0) {
      return row
    }
  }

  return null
}

export function isBoardFull(board: Board): boolean {
  return board[0].every((cell) => cell !== 0)
}

export function hasConnectFour(
  board: Board,
  startRow: number,
  startCol: number,
  player: Player,
): boolean {
  const directions: Array<[rowStep: number, colStep: number]> = [
    [0, 1],
    [1, 0],
    [1, 1],
    [1, -1],
  ]

  return directions.some(([rowStep, colStep]) => {
    const streak =
      1 +
      countDirection(board, startRow, startCol, rowStep, colStep, player) +
      countDirection(board, startRow, startCol, -rowStep, -colStep, player)

    return streak >= 4
  })
}

export function dropPiece(board: Board, currentPlayer: Player, col: number): ResolvedMove | null {
  if (col < 0 || col >= COLS) {
    return null
  }

  const row = findOpenRow(board, col)
  if (row === null) {
    return null
  }

  board[row][col] = currentPlayer
  const winner = hasConnectFour(board, row, col, currentPlayer) ? currentPlayer : null
  const isDraw = winner === null && isBoardFull(board)

  return {
    row,
    col,
    winner,
    isDraw,
    nextPlayer: currentPlayer === 1 ? 2 : 1,
  }
}

function countDirection(
  board: Board,
  startRow: number,
  startCol: number,
  rowStep: number,
  colStep: number,
  player: Player,
): number {
  let row = startRow + rowStep
  let col = startCol + colStep
  let count = 0

  while (
    row >= 0 &&
    row < ROWS &&
    col >= 0 &&
    col < COLS &&
    board[row][col] === player
  ) {
    count += 1
    row += rowStep
    col += colStep
  }

  return count
}
