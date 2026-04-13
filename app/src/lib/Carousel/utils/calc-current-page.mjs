import { wrap } from 'motion';

function calcCurrentPage(targetOffset, pageInsets, wrapInset, maxInset) {
    const targetInset = -targetOffset;
    const iteration = maxInset === null ? Math.floor(targetInset / wrapInset) : 0;
    const transformInset = iteration * wrapInset;
    for (let i = pageInsets.length - 1; i >= 0; i--) {
        const inset = pageInsets[i] + transformInset;
        const prevIndex = wrap(0, pageInsets.length, i - 1);
        const prevIteration = i === 0 ? iteration - 1 : iteration;
        const prevTransformInset = prevIteration * wrapInset;
        const prevInset = pageInsets[prevIndex] + prevTransformInset;
        const halfDistanceToPrev = (inset - prevInset) / 2;
        const nextIndex = wrap(0, pageInsets.length, i + 1);
        const nextIteration = i === pageInsets.length - 1 ? iteration + 1 : iteration;
        const nextTransformInset = nextIteration * wrapInset;
        const nextInset = pageInsets[nextIndex] + nextTransformInset;
        const halfDistanceToNext = (nextInset - inset) / 2;
        if (targetInset < nextInset - halfDistanceToNext &&
            targetInset >= prevInset + halfDistanceToPrev) {
            return i;
        }
    }
    return 0;
}

export { calcCurrentPage };
