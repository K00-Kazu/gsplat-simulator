#include "preview_viewport_widget.h"

#include <QPainter>
#include <QPainterPath>
#include <QPaintEvent>
#include <QPen>
#include <QRectF>
#include <QSizePolicy>

namespace
{
constexpr qreal kCornerMargin = 20.0;
constexpr qreal kGizmoRadius = 34.0;
constexpr qreal kGizmoLabelSize = 24.0;

QRectF buildAspectFitRect(const QSizeF& bounds, const QSizeF& imageSize)
{
    if (bounds.width() <= 0.0 || bounds.height() <= 0.0 || imageSize.width() <= 0.0 || imageSize.height() <= 0.0)
    {
        return {};
    }

    const qreal scale =
        qMin(bounds.width() / imageSize.width(), bounds.height() / imageSize.height());
    const QSizeF scaledSize(imageSize.width() * scale, imageSize.height() * scale);
    const QPointF topLeft(
        (bounds.width() - scaledSize.width()) / 2.0,
        (bounds.height() - scaledSize.height()) / 2.0);
    return QRectF(topLeft, scaledSize);
}

QVector3D safeNormalized(const QVector3D& vector, const QVector3D& fallback)
{
    if (vector.lengthSquared() <= 1e-6f)
    {
        return fallback.normalized();
    }

    return vector.normalized();
}
}  // namespace

PreviewViewportWidget::PreviewViewportWidget(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("previewViewport"));
    setMinimumSize(640, 360);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
}

void PreviewViewportWidget::setPreviewFrame(const QImage& image, qint64 frameId)
{
    latestFrame_ = image;
    latestFrameId_ = frameId;
    update();
}

void PreviewViewportWidget::setPreviewCameraState(const PreviewCameraState& state)
{
    latestCameraState_ = state;
    hasCameraState_ = true;
    update();
}

void PreviewViewportWidget::paintEvent(QPaintEvent* event)
{
    Q_UNUSED(event);

    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    painter.fillRect(rect(), QColor(QStringLiteral("#111418")));

    const QRectF viewportRect = rect().adjusted(0.5, 0.5, -0.5, -0.5);
    const QRectF imageRect = buildImageRect();
    if (latestFrame_.isNull() || imageRect.isEmpty())
    {
        paintEmptyState(painter, viewportRect);
        return;
    }

    paintFrame(painter, imageRect);
    paintOverlay(painter, imageRect);
}

QRectF PreviewViewportWidget::buildImageRect() const
{
    if (latestFrame_.isNull())
    {
        return {};
    }

    return buildAspectFitRect(size(), latestFrame_.size());
}

void PreviewViewportWidget::paintEmptyState(QPainter& painter, const QRectF& viewportRect) const
{
    QPainterPath backgroundPath;
    backgroundPath.addRoundedRect(viewportRect.adjusted(6.0, 6.0, -6.0, -6.0), 12.0, 12.0);

    painter.fillPath(backgroundPath, QColor(QStringLiteral("#161a20")));
    painter.setPen(QPen(QColor(QStringLiteral("#2f353d")), 1.0));
    painter.drawPath(backgroundPath);

    painter.setPen(QColor(QStringLiteral("#d2d6db")));
    painter.drawText(viewportRect, Qt::AlignCenter, QStringLiteral("No preview frame received yet."));
}

void PreviewViewportWidget::paintFrame(QPainter& painter, const QRectF& imageRect) const
{
    QPainterPath clipPath;
    clipPath.addRoundedRect(imageRect, 12.0, 12.0);
    painter.fillPath(clipPath, QColor(QStringLiteral("#161a20")));

    painter.save();
    painter.setClipPath(clipPath);
    painter.drawImage(imageRect, latestFrame_);
    painter.restore();

    painter.setPen(QPen(QColor(QStringLiteral("#2f353d")), 1.0));
    painter.drawRoundedRect(imageRect, 12.0, 12.0);
}

void PreviewViewportWidget::paintOverlay(QPainter& painter, const QRectF& imageRect) const
{
    paintPreviewBadge(painter, imageRect);
    paintGizmo(painter, imageRect);
}

void PreviewViewportWidget::paintPreviewBadge(QPainter& painter, const QRectF& imageRect) const
{
    const QString badgeText = hasCameraState_ && !latestCameraState_.cameraRole.isEmpty()
        ? QStringLiteral("%1 camera").arg(latestCameraState_.cameraRole)
        : QStringLiteral("Preview camera");
    const QRectF badgeRect(
        imageRect.left() + kCornerMargin,
        imageRect.top() + kCornerMargin,
        160.0,
        36.0);

    painter.save();
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(17, 20, 24, 210));
    painter.drawRoundedRect(badgeRect, 10.0, 10.0);
    painter.setPen(QColor(QStringLiteral("#e8eaed")));
    painter.drawText(badgeRect, Qt::AlignCenter, badgeText);
    painter.restore();
}

void PreviewViewportWidget::paintGizmo(QPainter& painter, const QRectF& imageRect) const
{
    // Preview frame and camera state arrive on separate topics, so exact frame_id
    // alignment is not guaranteed at the UI boundary. Render the latest preview
    // gizmo as soon as we have any valid camera state.
    if (!hasCameraState_ || latestFrameId_ < 0 || !latestCameraState_.gizmoEnabled)
    {
        return;
    }

    const QVector3D eye = latestCameraState_.eye;
    const QVector3D target = latestCameraState_.target;
    const QVector3D worldUp = safeNormalized(latestCameraState_.up, QVector3D(0.0f, 0.0f, 1.0f));
    const QVector3D forward = safeNormalized(target - eye, QVector3D(0.0f, 1.0f, 0.0f));
    const QVector3D right = safeNormalized(QVector3D::crossProduct(forward, worldUp), QVector3D(1.0f, 0.0f, 0.0f));
    const QVector3D trueUp = safeNormalized(QVector3D::crossProduct(right, forward), QVector3D(0.0f, 0.0f, 1.0f));

    const QPointF origin(imageRect.right() - 72.0, imageRect.bottom() - 72.0);

    const auto drawAxis = [&painter, &origin, &right, &trueUp](const QVector3D& axis, const QColor& color, const QString& label) {
        const QPointF direction(
            QVector3D::dotProduct(axis, right) * kGizmoRadius,
            -QVector3D::dotProduct(axis, trueUp) * kGizmoRadius);
        const QPointF endPoint = origin + direction;

        painter.setPen(QPen(color, 2.0, Qt::SolidLine, Qt::RoundCap));
        painter.drawLine(origin, endPoint);
        painter.setBrush(color);
        painter.drawEllipse(endPoint, 3.0, 3.0);
        painter.drawText(
            QRectF(
                endPoint.x() - kGizmoLabelSize / 2.0,
                endPoint.y() - kGizmoLabelSize / 2.0,
                kGizmoLabelSize,
                kGizmoLabelSize),
            Qt::AlignCenter,
            label);
    };

    painter.save();
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(17, 20, 24, 210));
    painter.drawRoundedRect(
        QRectF(imageRect.right() - 126.0, imageRect.bottom() - 126.0, 106.0, 106.0),
        12.0,
        12.0);
    painter.setBrush(QColor(QStringLiteral("#e8eaed")));
    painter.drawEllipse(origin, 3.5, 3.5);
    drawAxis(QVector3D(1.0f, 0.0f, 0.0f), QColor(QStringLiteral("#ea4335")), QStringLiteral("X"));
    drawAxis(QVector3D(0.0f, 1.0f, 0.0f), QColor(QStringLiteral("#34a853")), QStringLiteral("Y"));
    drawAxis(QVector3D(0.0f, 0.0f, 1.0f), QColor(QStringLiteral("#4285f4")), QStringLiteral("Z"));
    painter.setPen(QColor(QStringLiteral("#d2d6db")));
    painter.drawText(
        QRectF(imageRect.right() - 126.0, imageRect.bottom() - 150.0, 106.0, 20.0),
        Qt::AlignCenter,
        QStringLiteral("world %1-up").arg(latestCameraState_.worldUpAxis.toUpper()));
    painter.restore();
}
