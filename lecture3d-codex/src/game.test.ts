import { describe, expect, it } from 'vitest'
import {
  COLS,
  ROWS,
  createEmptyBoard,
  dropPiece,
  findOpenRow,
  hasConnectFour,
  isBoardFull,
  type Board,
} from './game'

describe('createEmptyBoard', () => {
  it('creates a 6x7 board filled with zeros', () => {
    const board = createEmptyBoard()

    expect(board).toHaveLength(ROWS)
    expect(board.every((row) => row.length === COLS)).toBe(true)
    expect(board.flat().every((cell) => cell === 0)).toBe(true)
  })
})

describe('findOpenRow', () => {
  it('returns the bottom row on an empty column', () => {
    const board = createEmptyBoard()

    expect(findOpenRow(board, 0)).toBe(ROWS - 1)
  })

  it('returns null when a column is full', () => {
    const board = createEmptyBoard()

    for (let row = 0; row < ROWS; row += 1) {
      board[row][3] = 1
    }

    expect(findOpenRow(board, 3)).toBeNull()
  })
})

describe('hasConnectFour', () => {
  it('detects horizontal wins', () => {
    const board = createEmptyBoard()
    board[5][0] = 1
    board[5][1] = 1
    board[5][2] = 1
    board[5][3] = 1

    expect(hasConnectFour(board, 5, 3, 1)).toBe(true)
  })

  it('detects vertical wins', () => {
    const board = createEmptyBoard()
    board[5][0] = 2
    board[4][0] = 2
    board[3][0] = 2
    board[2][0] = 2

    expect(hasConnectFour(board, 2, 0, 2)).toBe(true)
  })

  it('detects diagonal wins in both directions', () => {
    const boardA = createEmptyBoard()
    boardA[5][0] = 1
    boardA[4][1] = 1
    boardA[3][2] = 1
    boardA[2][3] = 1

    const boardB = createEmptyBoard()
    boardB[2][0] = 2
    boardB[3][1] = 2
    boardB[4][2] = 2
    boardB[5][3] = 2

    expect(hasConnectFour(boardA, 2, 3, 1)).toBe(true)
    expect(hasConnectFour(boardB, 5, 3, 2)).toBe(true)
  })
})

describe('dropPiece', () => {
  it('drops to the lowest available row and returns next player', () => {
    const board = createEmptyBoard()

    const move1 = dropPiece(board, 1, 4)
    const move2 = dropPiece(board, 2, 4)

    expect(move1?.row).toBe(5)
    expect(move1?.nextPlayer).toBe(2)
    expect(move2?.row).toBe(4)
    expect(move2?.nextPlayer).toBe(1)
  })

  it('returns null for out-of-range columns', () => {
    const board = createEmptyBoard()

    expect(dropPiece(board, 1, -1)).toBeNull()
    expect(dropPiece(board, 1, COLS)).toBeNull()
  })

  it('returns null for full columns', () => {
    const board = createEmptyBoard()

    for (let i = 0; i < ROWS; i += 1) {
      dropPiece(board, i % 2 === 0 ? 1 : 2, 2)
    }

    expect(dropPiece(board, 1, 2)).toBeNull()
  })

  it('marks a winning move', () => {
    const board = createEmptyBoard()
    dropPiece(board, 1, 0)
    dropPiece(board, 1, 1)
    dropPiece(board, 1, 2)

    const winningMove = dropPiece(board, 1, 3)

    expect(winningMove?.winner).toBe(1)
    expect(winningMove?.isDraw).toBe(false)
  })

  it('marks draw when board is filled without a winner', () => {
    const board: Board = [
      [2, 1, 2, 1, 2, 1, 2],
      [1, 2, 1, 2, 1, 2, 1],
      [2, 1, 2, 1, 2, 1, 2],
      [1, 2, 1, 2, 1, 2, 1],
      [2, 1, 2, 1, 2, 1, 2],
      [1, 2, 1, 2, 1, 2, 0],
    ]

    const lastMove = dropPiece(board, 2, 6)

    expect(lastMove).not.toBeNull()
    expect(lastMove?.winner).toBeNull()
    expect(lastMove?.isDraw).toBe(true)
  })
})

describe('isBoardFull', () => {
  it('returns true only when top row has no empty slots', () => {
    const board = createEmptyBoard()
    expect(isBoardFull(board)).toBe(false)

    for (let col = 0; col < COLS; col += 1) {
      board[0][col] = 1
    }

    expect(isBoardFull(board)).toBe(true)
  })
})
