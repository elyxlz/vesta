import { calcTotalItemLength, calcItemLength } from './calc-total-item-length.mjs';

function calcNumClones(visibleLength, itemPositions, gap) {
    const totalItemLength = calcTotalItemLength(itemPositions);
    const maxItemLength = Math.max(...itemPositions.map(calcItemLength));
    let count = 0;
    /**
     * A length where the largest item is out of the visible area.
     */
    let safeFillLength = 0;
    while (safeFillLength < visibleLength) {
        safeFillLength = (totalItemLength + gap) * (count + 1) - maxItemLength;
        count++;
    }
    return Math.max(count - 1, 0);
}

export { calcNumClones };
