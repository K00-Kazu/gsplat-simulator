#include "main_window.h"

#include "render_worker.h"

#include <algorithm>
#include <QDockWidget>
#include <QFontMetrics>
#include <QGridLayout>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QResizeEvent>
#include <QSizePolicy>
#include <QStatusBar>
#include <QVBoxLayout>
#include <QWidget>

namespace
{
constexpr double kCameraOffsetStep = 0.2;
}

MainWindow::MainWindow(QWidget* parent, bool autoSubscribe)
    : QMainWindow(parent)
{
    setWindowTitle("gsplat-simulator UI");
    resize(1280, 720);

    auto* central_widget = new QWidget(this);
    auto* layout = new QVBoxLayout(central_widget);
    layout->setContentsMargins(32, 32, 32, 32);
    layout->setSpacing(12);

    auto* title_label = new QLabel("gsplat-simulator UI", central_widget);
    title_label->setStyleSheet("font-size: 28px; font-weight: 700;");

    auto* subtitle_label = new QLabel(
        "Zenoh frame subscriber preview for render output",
        central_widget);
    subtitle_label->setWordWrap(true);
    subtitle_label->setStyleSheet("color: #5f6368; font-size: 14px;");

    preview_label_ = new QLabel("No frame received yet.", central_widget);
    preview_label_->setObjectName("previewLabel");
    preview_label_->setAlignment(Qt::AlignCenter);
    preview_label_->setMinimumSize(640, 360);
    preview_label_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    preview_label_->setStyleSheet(
        "background-color: #111418; color: #d2d6db; border: 1px solid #2f353d; border-radius: 12px;");

    layout->addWidget(title_label);
    layout->addWidget(subtitle_label);
    layout->addSpacing(12);
    layout->addWidget(preview_label_, 1);

    setCentralWidget(central_widget);

    auto* camera_controls_dock = new QDockWidget("Camera controls", this);
    camera_controls_dock->setObjectName("cameraControlsDock");
    camera_controls_dock->setAllowedAreas(Qt::LeftDockWidgetArea | Qt::RightDockWidgetArea);
    camera_controls_dock->setFeatures(QDockWidget::NoDockWidgetFeatures);

    auto* camera_controls_panel = new QWidget(camera_controls_dock);
    camera_controls_panel->setMinimumWidth(240);

    auto* panel_layout = new QVBoxLayout(camera_controls_panel);
    panel_layout->setContentsMargins(16, 16, 16, 16);
    panel_layout->setSpacing(12);

    auto* camera_hint_label = new QLabel(
        "Adjust the virtual camera offset for the render preview.",
        camera_controls_panel);
    camera_hint_label->setWordWrap(true);
    camera_hint_label->setStyleSheet("color: #5f6368; font-size: 13px;");

    camera_offset_label_ = new QLabel(camera_controls_panel);
    camera_offset_label_->setObjectName("cameraOffsetLabel");
    camera_offset_label_->setWordWrap(true);
    camera_offset_label_->setStyleSheet("color: #3c4043; font-size: 14px;");

    auto* camera_controls_layout = new QGridLayout();
    camera_controls_layout->setHorizontalSpacing(8);
    camera_controls_layout->setVerticalSpacing(8);

    auto* up_button = new QPushButton("Up", camera_controls_panel);
    auto* left_button = new QPushButton("Left", camera_controls_panel);
    auto* right_button = new QPushButton("Right", camera_controls_panel);
    auto* down_button = new QPushButton("Down", camera_controls_panel);

    camera_controls_layout->addWidget(up_button, 0, 1);
    camera_controls_layout->addWidget(left_button, 1, 0);
    camera_controls_layout->addWidget(right_button, 1, 2);
    camera_controls_layout->addWidget(down_button, 2, 1);

    connect(up_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(0.0, kCameraOffsetStep); });
    connect(left_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(-kCameraOffsetStep, 0.0); });
    connect(right_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(kCameraOffsetStep, 0.0); });
    connect(down_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(0.0, -kCameraOffsetStep); });

    panel_layout->addWidget(camera_hint_label);
    panel_layout->addWidget(camera_offset_label_);
    panel_layout->addLayout(camera_controls_layout);
    panel_layout->addStretch(1);

    camera_controls_dock->setWidget(camera_controls_panel);
    addDockWidget(Qt::RightDockWidgetArea, camera_controls_dock);

    auto* bottom_status_bar = new QStatusBar(this);
    bottom_status_bar->setObjectName("renderStatusBar");
    bottom_status_bar->setSizeGripEnabled(false);

    render_status_label_ = new QLabel("render subscriber: starting...", bottom_status_bar);
    render_status_label_->setObjectName("renderStatusLabel");
    render_status_label_->setStyleSheet("font-size: 12px; font-weight: 600; color: #5f6368;");

    render_detail_label_ = new QLabel(bottom_status_bar);
    render_detail_label_->setObjectName("renderDetailLabel");
    render_detail_label_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    render_detail_label_->setStyleSheet("font-size: 12px; color: #5f6368;");

    bottom_status_bar->addWidget(render_status_label_);
    bottom_status_bar->addWidget(render_detail_label_, 1);
    setStatusBar(bottom_status_bar);

    render_worker_ = new RenderWorker(this);
    connect(render_worker_, &RenderWorker::statusChanged, this, &MainWindow::applyRenderStatus);
    connect(render_worker_, &RenderWorker::frameReady, this, &MainWindow::applyPreviewFrame);
    if (autoSubscribe)
    {
        render_worker_->subscribe();
    }

    render_detail_text_ = QStringLiteral("Waiting for frame metadata and payload subscriptions to come online.");
    refreshRenderDetailLabel();
    refreshCameraOffsetLabel();
}

void MainWindow::applyRenderStatus(const QString& summary, const QString& detail, bool isError)
{
    render_status_label_->setText(summary);
    render_status_label_->setToolTip(summary);
    render_detail_text_ = detail;
    render_detail_label_->setToolTip(detail);
    refreshRenderDetailLabel();

    if (!isError)
    {
        render_status_label_->setStyleSheet("color: #137333; font-size: 12px; font-weight: 600;");
        return;
    }

    render_status_label_->setStyleSheet("color: #b3261e; font-size: 12px; font-weight: 600;");
}

void MainWindow::applyPreviewFrame(const QImage& image)
{
    latest_preview_image_ = image;
    refreshPreviewPixmap();
}

void MainWindow::refreshRenderDetailLabel()
{
    if (render_detail_label_ == nullptr)
    {
        return;
    }

    const int available_width = std::max(render_detail_label_->width(), 120);
    const QFontMetrics metrics(render_detail_label_->font());
    render_detail_label_->setText(metrics.elidedText(render_detail_text_, Qt::ElideRight, available_width));
}

void MainWindow::adjustCameraOffset(double deltaX, double deltaZ)
{
    camera_offset_x_ += deltaX;
    camera_offset_z_ += deltaZ;
    refreshCameraOffsetLabel();

    if (render_worker_ != nullptr)
    {
        render_worker_->requestCameraOffset(
            static_cast<float>(camera_offset_x_),
            0.0f,
            static_cast<float>(camera_offset_z_));
    }
}

void MainWindow::refreshPreviewPixmap()
{
    if (latest_preview_image_.isNull())
    {
        preview_label_->setText("No frame received yet.");
        preview_label_->setPixmap(QPixmap());
        return;
    }

    const QPixmap pixmap = QPixmap::fromImage(latest_preview_image_);
    preview_label_->setText({});
    preview_label_->setPixmap(pixmap.scaled(
        preview_label_->size(),
        Qt::KeepAspectRatio,
        Qt::SmoothTransformation));
}

void MainWindow::refreshCameraOffsetLabel()
{
    camera_offset_label_->setText(
        QStringLiteral("Camera offset (radius units): x=%1 y=%2 z=%3")
            .arg(camera_offset_x_, 0, 'f', 2)
            .arg(0.0, 0, 'f', 2)
            .arg(camera_offset_z_, 0, 'f', 2));
}

void MainWindow::resizeEvent(QResizeEvent* event)
{
    QMainWindow::resizeEvent(event);
    refreshRenderDetailLabel();
    refreshPreviewPixmap();
}
