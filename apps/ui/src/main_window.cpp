#include "main_window.h"

#include "render_worker.h"

#include <QGridLayout>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QResizeEvent>
#include <QSizePolicy>
#include <QVBoxLayout>
#include <QWidget>

namespace
{
constexpr double kCameraOffsetStep = 0.2;
}

MainWindow::MainWindow(QWidget* parent)
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

    render_status_label_ = new QLabel("render subscriber: starting...", central_widget);
    render_status_label_->setStyleSheet("font-size: 18px; font-weight: 600;");

    render_detail_label_ = new QLabel(
        "Waiting for frame metadata and payload subscriptions to come online.",
        central_widget);
    render_detail_label_->setWordWrap(true);
    render_detail_label_->setStyleSheet("color: #3c4043; font-size: 14px;");

    auto* camera_controls_label = new QLabel("Camera controls", central_widget);
    camera_controls_label->setStyleSheet("font-size: 18px; font-weight: 600;");

    camera_offset_label_ = new QLabel(central_widget);
    camera_offset_label_->setStyleSheet("color: #3c4043; font-size: 14px;");

    auto* camera_controls_layout = new QGridLayout();
    camera_controls_layout->setHorizontalSpacing(8);
    camera_controls_layout->setVerticalSpacing(8);

    auto* up_button = new QPushButton("Up", central_widget);
    auto* left_button = new QPushButton("Left", central_widget);
    auto* right_button = new QPushButton("Right", central_widget);
    auto* down_button = new QPushButton("Down", central_widget);

    camera_controls_layout->addWidget(up_button, 0, 1);
    camera_controls_layout->addWidget(left_button, 1, 0);
    camera_controls_layout->addWidget(right_button, 1, 2);
    camera_controls_layout->addWidget(down_button, 2, 1);

    connect(up_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(0.0, kCameraOffsetStep); });
    connect(left_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(-kCameraOffsetStep, 0.0); });
    connect(right_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(kCameraOffsetStep, 0.0); });
    connect(down_button, &QPushButton::clicked, this, [this]() { adjustCameraOffset(0.0, -kCameraOffsetStep); });

    preview_label_ = new QLabel("No frame received yet.", central_widget);
    preview_label_->setAlignment(Qt::AlignCenter);
    preview_label_->setMinimumSize(640, 360);
    preview_label_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    preview_label_->setStyleSheet(
        "background-color: #111418; color: #d2d6db; border: 1px solid #2f353d; border-radius: 12px;");

    layout->addWidget(title_label);
    layout->addWidget(subtitle_label);
    layout->addSpacing(12);
    layout->addWidget(render_status_label_);
    layout->addWidget(render_detail_label_);
    layout->addSpacing(12);
    layout->addWidget(camera_controls_label);
    layout->addWidget(camera_offset_label_);
    layout->addLayout(camera_controls_layout);
    layout->addSpacing(12);
    layout->addWidget(preview_label_, 1);

    setCentralWidget(central_widget);

    render_worker_ = new RenderWorker(this);
    connect(render_worker_, &RenderWorker::statusChanged, this, &MainWindow::applyRenderStatus);
    connect(render_worker_, &RenderWorker::frameReady, this, &MainWindow::applyPreviewFrame);
    render_worker_->subscribe();
    refreshCameraOffsetLabel();
}

void MainWindow::applyRenderStatus(const QString& summary, const QString& detail, bool isError)
{
    render_status_label_->setText(summary);
    render_detail_label_->setText(detail);

    if (!isError)
    {
        render_status_label_->setStyleSheet("color: #137333; font-size: 18px; font-weight: 600;");
        return;
    }

    render_status_label_->setStyleSheet("color: #b3261e; font-size: 18px; font-weight: 600;");
}

void MainWindow::applyPreviewFrame(const QImage& image)
{
    latest_preview_image_ = image;
    refreshPreviewPixmap();
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
    refreshPreviewPixmap();
}
