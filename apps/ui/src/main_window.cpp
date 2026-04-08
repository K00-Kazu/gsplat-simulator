#include "main_window.h"

#include "zenoh_smoke_test.h"

#include <QLabel>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>

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
        "Qt install verification and zenoh integration smoke test",
        central_widget);
    subtitle_label->setWordWrap(true);
    subtitle_label->setStyleSheet("color: #5f6368; font-size: 14px;");

    zenoh_status_label_ = new QLabel("zenoh smoke test: running...", central_widget);
    zenoh_status_label_->setStyleSheet("font-size: 18px; font-weight: 600;");

    zenoh_detail_label_ = new QLabel(
        "Opening a zenoh session and publishing a startup message.",
        central_widget);
    zenoh_detail_label_->setWordWrap(true);
    zenoh_detail_label_->setStyleSheet("color: #3c4043; font-size: 14px;");

    layout->addWidget(title_label);
    layout->addWidget(subtitle_label);
    layout->addSpacing(12);
    layout->addWidget(zenoh_status_label_);
    layout->addWidget(zenoh_detail_label_);
    layout->addStretch();

    setCentralWidget(central_widget);

    QTimer::singleShot(0, this, [this]() {
        applyZenohSmokeTestResult();
    });
}

void MainWindow::applyZenohSmokeTestResult()
{
    const ZenohSmokeResult result = runZenohSmokeTest();

    zenoh_status_label_->setText(result.summary);
    zenoh_detail_label_->setText(result.detail);

    if (result.success)
    {
        zenoh_status_label_->setStyleSheet("color: #137333; font-size: 18px; font-weight: 600;");
        return;
    }

    zenoh_status_label_->setStyleSheet("color: #b3261e; font-size: 18px; font-weight: 600;");
}
