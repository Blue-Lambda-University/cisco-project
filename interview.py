import numpy as np


def normalize_images(images: np.ndarray) -> np.ndarray:
    '''images: numpy array of shape (N, H, W)
       return: normalized float32 array'''

    # Convert to float32 to allow for decimal values
    images_float = images.astype(np.float32)

    # Rescale pixel values to the [0, 1] range
    normalized = images_float / 255.0

    return normalized