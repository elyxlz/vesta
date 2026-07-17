import ExpoModulesCore
import UIKit

private enum MessageTailSide: String, Enumerable {
  case none
  case leading
  case trailing
}

private struct MessageMenuAction: Record {
  @Field var id: String = ""
  @Field var title: String = ""
  @Field var systemImage: String?
  @Field var destructive: Bool = false
  @Field var disabled: Bool = false
}

private struct PreviewGeometryKey: Equatable {
  let bounds: CGRect
  let tailSide: String
  let tailOverhang: CGFloat
  let cornerRadius: CGFloat
}

private final class VestaMessageMenuView: ExpoView,
  UIContextMenuInteractionDelegate
{
  let onAction = EventDispatcher()

  var actions: [MessageMenuAction] = [] {
    didSet {
      interaction.updateVisibleMenu { [weak self] _ in
        self?.makeMenu() ?? UIMenu()
      }
    }
  }
  var tailSide: MessageTailSide = .none
  var tailOverhang: CGFloat = 0
  var previewCornerRadius: CGFloat = 22
  var bubbleFillColor: UIColor = .clear
  var bubbleStrokeColor: UIColor = .clear
  var bubbleStrokeWidth: CGFloat = 0

  private lazy var interaction = UIContextMenuInteraction(delegate: self)
  private let bubbleLayer = CAShapeLayer()
  private weak var directChild: UIView?
  private var cachedGeometryKey: PreviewGeometryKey?
  private var cachedVisiblePath: UIBezierPath?

  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    backgroundColor = .clear
    clipsToBounds = false
    isOpaque = false
    bubbleLayer.fillColor = UIColor.clear.cgColor
    bubbleLayer.strokeColor = UIColor.clear.cgColor
    bubbleLayer.lineJoin = .round
    bubbleLayer.lineCap = .round
    bubbleLayer.zPosition = -1
    layer.insertSublayer(bubbleLayer, at: 0)
    addInteraction(interaction)
  }

  override func layoutSubviews() {
    super.layoutSubviews()
    updateBubbleLayer()
  }

  override func traitCollectionDidChange(
    _ previousTraitCollection: UITraitCollection?
  ) {
    super.traitCollectionDidChange(previousTraitCollection)
    updateBubbleLayer()
  }

  override func mountChildComponentView(
    _ childComponentView: UIView,
    index: Int
  ) {
    guard directChild == nil else {
      return
    }
    directChild = childComponentView
    super.mountChildComponentView(childComponentView, index: index)
    layer.insertSublayer(bubbleLayer, below: childComponentView.layer)
  }

  override func unmountChildComponentView(_ child: UIView, index: Int) {
    guard directChild === child else {
      return
    }
    directChild = nil
    super.unmountChildComponentView(child, index: index)
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configurationForMenuAtLocation location: CGPoint
  ) -> UIContextMenuConfiguration? {
    UIContextMenuConfiguration(
      identifier: nil,
      previewProvider: nil,
      actionProvider: { [weak self] _ in
        self?.makeMenu()
      }
    )
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configuration: UIContextMenuConfiguration,
    highlightPreviewForItemWithIdentifier identifier: any NSCopying
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    configuration: UIContextMenuConfiguration,
    dismissalPreviewForItemWithIdentifier identifier: any NSCopying
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    previewForHighlightingMenuWithConfiguration configuration:
      UIContextMenuConfiguration
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  func contextMenuInteraction(
    _ interaction: UIContextMenuInteraction,
    previewForDismissingMenuWithConfiguration configuration:
      UIContextMenuConfiguration
  ) -> UITargetedPreview? {
    makeTargetedPreview()
  }

  private func makeMenu() -> UIMenu {
    let children = actions.map { action in
      var attributes: UIMenuElement.Attributes = []
      if action.destructive {
        attributes.insert(.destructive)
      }
      if action.disabled {
        attributes.insert(.disabled)
      }

      return UIAction(
        title: action.title,
        image: action.systemImage.flatMap(UIImage.init(systemName:)),
        attributes: attributes,
        handler: { [weak self] _ in
          self?.onAction(["id": action.id])
        }
      )
    }
    return UIMenu(title: "", children: children)
  }

  private func makeTargetedPreview() -> UITargetedPreview? {
    guard window != nil else {
      return nil
    }

    layoutIfNeeded()
    let parameters = UIPreviewParameters()
    parameters.backgroundColor = .clear
    parameters.visiblePath = makeVisiblePath()
    return UITargetedPreview(view: self, parameters: parameters)
  }

  private func updateBubbleLayer() {
    guard !bounds.isEmpty else {
      return
    }

    CATransaction.begin()
    CATransaction.setDisableActions(true)
    bubbleLayer.frame = bounds
    bubbleLayer.path = makeVisiblePath().cgPath
    bubbleLayer.fillColor = bubbleFillColor.resolvedColor(
      with: traitCollection
    ).cgColor
    bubbleLayer.strokeColor = bubbleStrokeColor.resolvedColor(
      with: traitCollection
    ).cgColor
    bubbleLayer.lineWidth = bubbleStrokeWidth
    CATransaction.commit()
  }

  private func makeVisiblePath() -> UIBezierPath {
    let geometryKey = PreviewGeometryKey(
      bounds: bounds,
      tailSide: tailSide.rawValue,
      tailOverhang: tailOverhang,
      cornerRadius: previewCornerRadius
    )
    if geometryKey == cachedGeometryKey, let cachedVisiblePath {
      return cachedVisiblePath
    }

    let overhang = max(0, min(tailOverhang, bounds.width))
    let bodyRect: CGRect
    bodyRect = bounds.inset(
      by: UIEdgeInsets(
        top: 0,
        left: overhang,
        bottom: 0,
        right: overhang
      )
    )

    // CALayer keeps the configured radius when opposite corners overlap; it
    // does not replace it with half the current view height. Keeping this
    // constant is important when a one-line bubble grows to multiple lines.
    let radius = max(0, previewCornerRadius)
    let bodyPath = makeContinuousRoundedRectPath(
      rect: bodyRect,
      radius: radius
    )

    let visiblePath: UIBezierPath
    switch tailSide {
    case .leading:
      visiblePath = union(
        bodyPath,
        with: makeLeadingTailPath(bodyRect: bodyRect)
      )
    case .trailing:
      visiblePath = union(
        bodyPath,
        with: makeTrailingTailPath(bodyRect: bodyRect)
      )
    case .none:
      visiblePath = bodyPath
    }
    cachedGeometryKey = geometryKey
    cachedVisiblePath = visiblePath
    return visiblePath
  }

  private func makeContinuousRoundedRectPath(
    rect: CGRect,
    radius: CGFloat
  ) -> UIBezierPath {
    guard radius > 0, !rect.isEmpty else {
      return UIBezierPath(rect: rect)
    }

    // These are UIKit's continuous-corner control points. Unlike a circular
    // rounded rect, the curve eases into each edge over a longer distance.
    // That is the same corner style React Native renders for
    // `borderCurve: "continuous"` on the message bubble.
    let edgeExtent = 1.52866483 * radius
    let cornerCurve = UIBezierPath()
    cornerCurve.move(to: CGPoint(x: edgeExtent, y: 0))
    cornerCurve.addCurve(
      to: CGPoint(x: 0.63149399 * radius, y: 0.07491139 * radius),
      controlPoint1: CGPoint(x: 1.08849323 * radius, y: 0),
      controlPoint2: CGPoint(x: 0.86840689 * radius, y: 0)
    )
    cornerCurve.addCurve(
      to: CGPoint(x: 0.07491139 * radius, y: 0.63149399 * radius),
      controlPoint1: CGPoint(
        x: 0.37282392 * radius,
        y: 0.16905899 * radius
      ),
      controlPoint2: CGPoint(
        x: 0.16905899 * radius,
        y: 0.37282392 * radius
      )
    )
    cornerCurve.addCurve(
      to: CGPoint(x: 0, y: edgeExtent),
      controlPoint1: CGPoint(x: 0, y: 0.86840689 * radius),
      controlPoint2: CGPoint(x: 0, y: 1.08849323 * radius)
    )

    let corners: [(CGAffineTransform, [CGPoint])] = [
      (
        CGAffineTransform(
          a: 1,
          b: 0,
          c: 0,
          d: 1,
          tx: rect.minX,
          ty: rect.minY
        ),
        [
          CGPoint(x: rect.minX, y: rect.maxY),
          CGPoint(x: rect.maxX, y: rect.maxY),
          CGPoint(x: rect.maxX, y: rect.minY),
        ]
      ),
      (
        CGAffineTransform(
          a: -1,
          b: 0,
          c: 0,
          d: 1,
          tx: rect.maxX,
          ty: rect.minY
        ),
        [
          CGPoint(x: rect.maxX, y: rect.maxY),
          CGPoint(x: rect.minX, y: rect.maxY),
          CGPoint(x: rect.minX, y: rect.minY),
        ]
      ),
      (
        CGAffineTransform(
          a: 1,
          b: 0,
          c: 0,
          d: -1,
          tx: rect.minX,
          ty: rect.maxY
        ),
        [
          CGPoint(x: rect.minX, y: rect.minY),
          CGPoint(x: rect.maxX, y: rect.minY),
          CGPoint(x: rect.maxX, y: rect.maxY),
        ]
      ),
      (
        CGAffineTransform(
          a: -1,
          b: 0,
          c: 0,
          d: -1,
          tx: rect.maxX,
          ty: rect.maxY
        ),
        [
          CGPoint(x: rect.maxX, y: rect.minY),
          CGPoint(x: rect.minX, y: rect.minY),
          CGPoint(x: rect.minX, y: rect.maxY),
        ]
      ),
    ]

    // Each corner is a clipping constraint rather than an independent patch.
    // Intersecting them preserves the configured radius even when the upper
    // and lower continuous curves overlap on a compact bubble.
    return corners.reduce(UIBezierPath(rect: rect)) { bodyPath, corner in
      let constraint = cornerCurve.copy() as! UIBezierPath
      constraint.apply(corner.0)
      corner.1.forEach(constraint.addLine)
      constraint.close()
      return UIBezierPath(
        cgPath: bodyPath.cgPath.intersection(constraint.cgPath)
      )
    }
  }

  private func union(
    _ path: UIBezierPath,
    with otherPath: UIBezierPath
  ) -> UIBezierPath {
    UIBezierPath(cgPath: path.cgPath.union(otherPath.cgPath))
  }

  private func makeLeadingTailPath(bodyRect: CGRect) -> UIBezierPath {
    let origin = CGPoint(
      x: bodyRect.minX - tailOverhang,
      y: bodyRect.maxY - 16
    )
    let path = UIBezierPath()
    path.move(to: CGPoint(x: origin.x + 26, y: origin.y + 16))
    path.addLine(to: CGPoint(x: origin.x + 6, y: origin.y + 1))
    path.addCurve(
      to: CGPoint(x: origin.x + 1, y: origin.y + 15),
      controlPoint1: CGPoint(x: origin.x + 6, y: origin.y + 10),
      controlPoint2: CGPoint(x: origin.x + 5, y: origin.y + 14)
    )
    path.addLine(to: CGPoint(x: origin.x, y: origin.y + 15))
    path.addCurve(
      to: CGPoint(x: origin.x + 12, y: origin.y + 12),
      controlPoint1: CGPoint(x: origin.x + 6, y: origin.y + 16),
      controlPoint2: CGPoint(x: origin.x + 9, y: origin.y + 14)
    )
    path.addCurve(
      to: CGPoint(x: origin.x + 26, y: origin.y + 16),
      controlPoint1: CGPoint(x: origin.x + 16, y: origin.y + 15),
      controlPoint2: CGPoint(x: origin.x + 21, y: origin.y + 16)
    )
    path.close()
    // Mirroring the SVG reverses its winding. Reverse it again so appending
    // it to the rounded body creates one nonzero-fill preview shape instead
    // of subtracting the overlapping portion.
    return path.reversing()
  }

  private func makeTrailingTailPath(bodyRect: CGRect) -> UIBezierPath {
    let origin = CGPoint(x: bodyRect.maxX - 21, y: bodyRect.maxY - 16)
    let path = UIBezierPath()
    path.move(to: CGPoint(x: origin.x, y: origin.y + 16))
    path.addLine(to: CGPoint(x: origin.x + 20, y: origin.y + 2))
    path.addCurve(
      to: CGPoint(x: origin.x + 25, y: origin.y + 15),
      controlPoint1: CGPoint(x: origin.x + 20, y: origin.y + 11),
      controlPoint2: CGPoint(x: origin.x + 21, y: origin.y + 14)
    )
    path.addLine(to: CGPoint(x: origin.x + 26, y: origin.y + 15))
    path.addCurve(
      to: CGPoint(x: origin.x + 15, y: origin.y + 12),
      controlPoint1: CGPoint(x: origin.x + 20, y: origin.y + 16),
      controlPoint2: CGPoint(x: origin.x + 17, y: origin.y + 14)
    )
    path.addCurve(
      to: CGPoint(x: origin.x, y: origin.y + 16),
      controlPoint1: CGPoint(x: origin.x + 11, y: origin.y + 15),
      controlPoint2: CGPoint(x: origin.x + 5, y: origin.y + 16)
    )
    path.close()
    return path
  }
}

public final class VestaMessageMenuModule: Module {
  public func definition() -> ModuleDefinition {
    Name("VestaMessageMenu")

    View(VestaMessageMenuView.self) {
      Prop("actions") {
        (view: VestaMessageMenuView, actions: [MessageMenuAction]) in
        view.actions = actions
      }
      Prop("tailSide") {
        (view: VestaMessageMenuView, side: MessageTailSide) in
        view.tailSide = side
        view.setNeedsLayout()
      }
      Prop("tailOverhang") {
        (view: VestaMessageMenuView, overhang: Double) in
        view.tailOverhang = CGFloat(overhang)
        view.setNeedsLayout()
      }
      Prop("previewCornerRadius") {
        (view: VestaMessageMenuView, radius: Double) in
        view.previewCornerRadius = CGFloat(radius)
        view.setNeedsLayout()
      }
      Prop("bubbleFillColor") {
        (view: VestaMessageMenuView, color: UIColor) in
        view.bubbleFillColor = color
        view.setNeedsLayout()
      }
      Prop("bubbleStrokeColor") {
        (view: VestaMessageMenuView, color: UIColor) in
        view.bubbleStrokeColor = color
        view.setNeedsLayout()
      }
      Prop("bubbleStrokeWidth") {
        (view: VestaMessageMenuView, width: Double) in
        view.bubbleStrokeWidth = CGFloat(width)
        view.setNeedsLayout()
      }
      Events("onAction")
    }
  }
}
