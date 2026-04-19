function calcItemLength(itemPosition) {
  return itemPosition.end - itemPosition.start;
}
function calcTotalItemLength(itemPositions) {
  return itemPositions[itemPositions.length - 1].end - itemPositions[0].start;
}

export { calcItemLength, calcTotalItemLength };
